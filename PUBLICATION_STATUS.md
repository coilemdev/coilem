# Release status

Updated November 6, 2026: the source candidate is **coilEM 0.5.1 Developer
Preview**, with **Magneto2D 0.4.0**. The app/frontend versions are bumped
before the preparation freeze `freeze/v0.5.1-rc1`. **Release qualification
and publication remain pending.** The [release plan](docs/RELEASE_0_5_1.md)
and [candidate plan](benchmarks/v0.5.1/candidate-plan.json) track identities
and remaining gates. Version 0.5.0 was published on November 3, 2026.

## Current evidence

The [combined Windows native/FEMM evidence](benchmarks/windows-v051-20261105-a4f9f4d/README.md)
measures the clean #190 integration merge `a4f9f4d`:

- Native A–D: 52 supported jobs, 46 PASS, one planned unsupported legacy ORNL
  Prius, and 336/336 gates PASS against the unchanged reviewed references.
- Overnight FEMM: all 46 fresh reference cases complete, comparison 46 PASS
  and 336/336 gates PASS. All 46 waveforms exactly match the reviewed
  references. One failed readiness attempt was successfully retried and is
  retained with its hashes. Native fields came from the same-commit run above.
- Proposed cogging: 12 native cases and 17 fresh FEMM sweeps / 425 fields.
  Original baseline results remain 9 PASS / 3 FAIL; selected refined
  references give 10 PASS / 2 YELLOW. All five finer-reference controls pass
  their reference self-checks. Fresh references remain REVIEW_REQUIRED.

The separate optional A–D repeat stopped at the owner's request is retained
as history. It is not the complete overnight run and supplies no reference
values to the earlier native-vs-reviewed comparison.

## Gates before the v0.5.1 publication tag

- Review Phase E references and their original self-check failures; resolve
  or explicitly accept supported coverage for the two YELLOW cases.
- Finish Phase E registration/default-command coverage after review.
- Complete the required matching Windows/macOS and Prius qualification and
  publish accepted platform records with frozen source/input identities.
- Pass the actual release qualification gate, development CI, dependency
  audits, all four non-publishing wheel targets and installed-package/browser
  acceptance. Preserve exact tested commits and workflow links.
- Obtain owner release acceptance before the `v0.5.1` tag and protected
  publication workflow.

The preparation tag does not trigger publication. Existing reports keep
their measured commit. Unchanged guarded physics hashes support provenance
review; they do not create new platform measurements or complete candidate
qualification. Linux/Python 3.15 smoke coverage does not establish full
numerical parity. Output qualification statuses and fixed gates are unchanged.

## Historical qualification

The [v0.5.0 evidence index](benchmarks/v0.5.0/README.md) and its
[passing release assessment](benchmarks/v0.5.0/release-qualification.json)
remain bound to candidate `88aae101`. Windows and macOS each record 46 PASS
and 336/336 gates; the complete exact-candidate Prius audit passes all ten
software checks. The [v0.4.0 history](benchmarks/v0.4.0/README.md) and original
platform identities are preserved. These historical assessments do not
qualify v0.5.1. New hardware correlation #69/#82 remains deferred; CREATOR
#90 and named presets #127 are outside this release preparation.
