# Qualification collection

The optional [Phase G loss benchmark](../benchmarks/phase-g-v1/README.md) has
its own four fixtures and Windows FEMM runner. It runs Magneto2D first and
does not change the A–F requests, references or release regression collection.
For 5.9, [stator iron and DC copper](../benchmarks/phase-g-v1/STATOR_COPPER_59.md)
have a separate electrical-cycle qualification; rotor loss remains experimental.

The release benchmark workflow builds Magneto2D once on each selected platform,
then measures eight balanced A–F groups and four Prius groups concurrently.
Every group uses the exact same clean candidate, locked Python environment and
binary. The join verifies complete coverage, requests and result hashes before
building a derived report. It rejects duplicate, missing, failed or mixed runs.
The source runs and their requests are never rewritten.

Dispatch `release-benchmarks.yml` on the candidate branch, select both platforms,
and use its full immutable candidate SHA. Build artifacts must be installed at
the standard solver path; setting `COILEM_MAGNETO2D_BINARY` would invalidate
source verification. Full collection is separate from the existing smoke test.
The 45-minute wall-time goal needs measurement on both hosted runner pools;
queue time and platform concurrency limits can affect it. Collection jobs have
a 90-minute safety limit so the timing target does not truncate valid fields.
Standard runners are retained; actual wall times are reported separately.

The `sector` collection measures the same groups as sectors: the A-F suite of
protocol 1.11.0 (`benchmarks/af-v1.11-sector`), graded against the same frozen
references, and every Prius job with `symmetry` set to `auto`. Its join reports
which cases solved a sector. It is evidence for sector solves and does not
replace the `registered` full-motor collection.

Use dispatch input `reuse_run` with the original collection run ID and its exact
measured candidate SHA to rebuild the joins without any field solves. The
workflow uses its own current download tooling while grading with the frozen
candidate's backend. This also recovers legacy artifacts that bundled large
raw archives with compact inputs. Downloads are staged one shard at a time;
redundant temporary archive copies are removed before the next download, while
the originals remain on the server. Prius retained inputs are verified and linked
into the join without a second physical copy.
Join jobs allow 45 minutes for legacy artifact transfers and verification. The
runner input also selects a single platform in join-only mode, so a successful
platform's existing joined artifact can be retained without repeating its join.

If a shard times out, dispatch with `source_run` and a `retry_shards` JSON array
of `platform/shard` IDs. Repairs download the original binary and require the
same candidate and execution identity. Native jobs use verified resume;
Prius jobs preserve verified completed cases and collect only missing cases
through the frozen candidate's own collector. The derived registration records
the parent and case hashes. Failed attempts remain in raw artifacts. Finish
with a join-only dispatch using `reuse_run` plus `supplement_runs` (a JSON array
of repair-run IDs); every original request and result keeps its measured bytes.

## Disk and retention

Keep output outside the checkout. A–F jobs use `--archive-runtime`: every raw
runtime is compressed, read back and checked file by file before deleting its
temporary directory. Prius retains its existing independently hashed field
copies and also removes its live cache after each completed job. Archives and
retained fields stay in workflow artifacts for 90 days. Failed uploads do not
turn a partial collection into qualification evidence.

Commit compact reports, waveform measurements, source identities and hash
receipts only. Keep these permanently: an expired artifact link is not a
replacement for a reproducible numerical record. Do not commit raw meshes,
field arrays, live caches or archives. The compact report is small, but the
active solve can exceed 1 GB (1.604 GB observed in a cogging case); this workflow
does not claim a 1 GB peak-disk bound. Compression prevents full-suite cache
accumulation, rather than reducing mesh size or numerical coverage.

Phase E remains a separately registered analysis. Refreshing A–D or the Prius
software reference does not qualify cogging, torque–speed maps or other
unmeasured outputs. No source guard, numerical gate or tolerance is removed.

## Collecting a platform locally

Hosted macOS runners are sometimes not assigned to a job. When that blocks a
collection, measure that platform on a local machine of the same kind. The
evidence gate checks source hashes, the measured commit, coverage and verdicts;
it does not need a workflow run or a particular OS version.

From a clean checkout at the candidate, with the locked environment installed
(`pip install -r requirements.lock`, then `pip install -e ".[dev]"`):

```bash
python -m tools.qualify_local --candidate <full SHA> --directory ~/coilem-qualification
```

This builds Magneto2D with the workflow's pinned toolchain, measures the twelve
shards in series, keeps the compact part of each and joins them. On an Apple
silicon laptop the collection takes about an hour and needs about 6 GB free at
its peak. It stops before a shard when less than 5 GB is free; rerun the same
command to continue from the first unfinished shard. Keep the machine on mains
power and awake.

All twelve shards of a platform must come from one machine. The join rejects a
mixed identity, so a local machine cannot fill in single shards beside hosted
ones. `retry_shards` also cannot repair a shard that never started, because it
has no earlier artifact to resume from.

The other platform still comes from the workflow. If its shards finished but
the join was skipped, rejoin it alone, then download the result:

```bash
gh workflow run release-benchmarks.yml --ref <branch> -f runner=windows-2022 -f candidate=<full SHA> -f reuse_run=<collection run ID>
gh run download <join run ID> --name benchmark-joined-windows-2022 --dir ~/coilem-qualification/windows
```

Then compare and publish with tooling from the PR base, as the publication job
does. `<base>` is a checkout of the PR base and `<head>` a checkout of the PR
branch, which may be ahead of the candidate by non-physics commits:

```bash
cd <base>
python -m tools.qualification_carry --root <head> --baseline . --windows ~/coilem-qualification/windows --macos ~/coilem-qualification/qualification --out ~/coilem-qualification/prepared
python -m tools.qualification_publish --root <head> --publication ~/coilem-qualification/prepared/publication --candidate <full SHA>
python <head>/tools/verify_snapshot.py --publication
git -C <head> add benchmarks snapshot-manifest.json
git -C <head> commit -m 'Publish measured qualification evidence'
git -C <head> push origin HEAD:<branch>
```

Moved values stop at `OWNER_REVIEW_REQUIRED` exactly as in the workflow.

The published reports name no local path. Reports record where the solver
cache was; under a home directory that names the machine's user, so the
comparison step replaces such paths with `<local path>` in the copies it
prepares and writes `publication-projection.json` with the original and
published hashes. That receipt also carries `local-collection.json`, which
states that the platform was collected locally. The raw fields of a local
collection are not retained.

## PR evidence gate

`python -m tools.physics_impact --base <base-sha>` compares the union of the old
and new source registries, including the Prius-specific sources. Removing a
registry entry cannot hide a changed source. Changes to registered suite or
reference contracts also require evidence. A physics PR passes when the strict
release check accepts its current-tree Windows, macOS and Prius reports, or when
a [sentinel collection](#sentinel-collection-for-small-changes) of the current
tree reproduces the full records.
The check binds measurements to source identities, not subsequent metadata-only
publication commits. Historical unit tests replay their original records;
they never promote those records to qualify a changed build.

Ready physics PRs start the parallel workflow automatically. Draft PRs can use
workflow dispatch. After v0.5.1 lands on `main`, make
`qualification evidence required` a required status check there, enable required code-owner review, and
protect the qualification rules listed in `.github/CODEOWNERS`. Merely committing
a workflow or CODEOWNERS file cannot enable those repository settings.
The release integration branch stays open for pending physics PRs and their
eventual frozen candidate qualification; its checks are informational.

PR #190 is a one-time, owner-approved integration exception: its evidence check,
automatic PR collection and publication are skipped. Run the full Windows/macOS
A–D and Prius collection from its exact `main` merge commit instead. Qualification
remains pending until matching evidence is accepted. This exception does not
apply to other PRs, runtime source guards or release/publication gates.

Later metadata-only pushes reuse compatible in-progress or completed PR
collections. The cache key includes guarded sources, registered contracts,
collector/grader code and the locked collection environment. It does not
replace the runtime source guard. Reuse verifies ancestry and retains the
original measured commit; an advanced physics identity cannot use old fields.

## Measured carry-forward

After both platforms finish, trusted tooling from the PR base compares the new
run to the previous record and the hash-bound approved reports in
`benchmarks/qualification-policy.json`. A ready result contains newly measured
records and regenerated reports, with the real field candidate and unchanged
FEMM provenance. The publisher commits compact evidence to the PR branch and
explicitly dispatches CI for that publication commit (a token-generated push
does not itself trigger another Actions run). An advanced PR head cannot be
overwritten. Fork PRs receive measurements as artifacts; write-back is limited
to branches in this repository.

The fast path checks existing torque/Back-EMF tolerances plus d/q flux values;
its additional replay tolerances are explicit in the owner-controlled policy.
Cogging records have their own p-p/H1 metrics. These are replay comparisons,
not wider FEMM accuracy gates. The fixed approved baseline prevents cumulative
drift through successive automatic updates.

Moved values produce `REVIEW.md`, `comparison.csv` (previous, new, approved and
FEMM values), and `decision.json`; they do not publish. After reviewing the
specific measurements, the owner can rerun `tools.qualification_carry` with
`--accept-moved`. That flag never overrides changed verdicts, failed FEMM gates,
incomplete Prius checks or incompatible reference contracts. Replacing approved
anchors is a separate owner-reviewed policy change, not an automatic reset.

Reference reuse checks the registered suite, requests, material/geometry/source
interpretation and metric definitions against the approved report. Changed
reference contracts produce `REFERENCE_REVIEW_REQUIRED`. The immutable bundle
is never retagged or rewritten to name a new candidate. The zero-solve candidate
join supports `--reuse-reviewed-reference` only after this compatibility check.

A change to a reference-sensitive source file, such as a new request option in
`backend/models/config.py`, also stops at `REFERENCE_REVIEW_REQUIRED`, even when
no value moves. After reviewing the listed files, the owner can rerun
`tools.qualification_carry` with `--reference-reviewed`. Each platform's
`reference-reuse.json` and the carry receipt then record every reviewed file
with its approved and candidate hash. The flag accepts changed source files
only: a changed suite, reference bundle, case coverage or registered request
has no override, and moved values still need `--accept-moved`. The automatic
publication job never passes either flag. Later comparisons keep reporting the
same files until the approved reports in `benchmarks/qualification-policy.json`
are replaced by ones measured with them, which is a separate owner-reviewed
policy change.

The public qualification basis and report path follow the primary registered
record. The release gate still requires actual matching Windows/macOS/Prius
measurements; changing hashes alone cannot qualify a build. A weekly workflow
compares fresh measurements and opens one issue for unexplained drift.

## Sentinel collection for small changes

Most physics PRs are expected to move no value: a refactor, a new option that
is off by default, a change to a path the benchmark requests do not take. For
those, a sentinel collection measures 22 of the 68 supported cases and two of
the 17 Prius jobs, with the unchanged full-grid requests, and compares them
with the full record of the same platform. It is about a third of the case
time of a full collection and needs five jobs per platform, not twelve.

`benchmarks/qualification-sentinel.json` names the cases and jobs. Together
they exercise every rotor family, winding layout, analysis lane, modifier
(no load, current angle, magnet temperature, tooth shoes, corner refinement,
angled magnets, chorded winding, parallel paths), mesh density and slot/pole
combination that the registered suite solves. `tests/test_qualification_sentinel.py`
fails when a suite change leaves one of these uncovered, so a new case family
needs a sentinel case before it can rely on this path.

The comparison is strict because the coverage is partial:

- **macOS** must reproduce the full record exactly: every waveform sample and
  every summary value (torque, back-EMF, flux densities, d/q flux linkages,
  losses, resistance), within 1e-9 of the series peak and never tighter than
  1e-12. macOS results are bit-reproducible across runs, machines and commits
  that leave the physics alone, so any larger difference is a real change.
- **Windows** uses the replay tolerances of the full comparison on the gated
  values and d/q flux linkages, against both the previous record and the
  approved baseline. Hosted Windows runners move some values by up to 0.2% of
  the waveform peak between runs of unchanged code, so an exact rule would
  fail without cause.
- Verdicts, gate statuses, solved requests, the suite, the reference bundle
  and the pinned Gmsh and meshio must be the full record's. Wall times and
  run metadata are not compared.

Collect on a runner by dispatching `release-benchmarks.yml` with
`collection: sentinel`, or locally:

```bash
python -m tools.qualify_local --collection sentinel --candidate <full SHA> --directory ~/coilem-sentinel
```

Then compare and publish with tooling from the PR base, as for a full
collection. Either platform can be compared and published alone:

```bash
cd <base>
python -m tools.qualification_sentinel compare --root <head> --baseline . --windows ~/coilem-sentinel/windows --macos ~/coilem-sentinel/qualification --out ~/coilem-sentinel/prepared
python -m tools.qualification_sentinel publish --publication ~/coilem-sentinel/prepared/publication --root <head>
python <head>/tools/verify_snapshot.py --publication
git -C <head> add benchmarks/sentinel snapshot-manifest.json
git -C <head> commit -m 'Publish sentinel qualification evidence'
```

`compare` ends in one of four states. `UNCHANGED` stages one compact evidence
file per platform under `benchmarks/sentinel/`. `MOVED` lists the values that
differ in `REVIEW.md`; the change needs the full collection and the normal
carry-forward review, and there is no flag to accept a moved sentinel value.
`REFERENCE_REVIEW_REQUIRED` means a reference-sensitive source file changed;
after reviewing the listed files the owner can rerun with
`--reference-reviewed`, exactly as for a full collection, and a changed request
has no override. `INVALID` means the collection is incomplete, dirty, mixed or
measured from other sources.

The PR evidence gate accepts committed sentinel evidence only when it re-checks
all of this against the current tree: the evidence names the current sentinel
definition, the current full record and the current physics sources, and the
stored values still match the full record's report. The platform records are
not rewritten. They keep naming the commit that the full collection measured.

Sentinel evidence never qualifies a release. `tools.release.qualification`
does not read it, so a release candidate still needs the full Windows, macOS
and Prius collection at its frozen commit. The app's own qualification status
also keeps following the full records. A sentinel pass says that the measured
subset did not move; it cannot rule out a change that only affects a case
outside the subset, which the next full collection would catch.

Item 4 of #194 is deliberately excluded: the physics source registry remains
unchanged, no solver modules are split, and dependency identity/fingerprints
are not introduced here. Changed configuration/model code may therefore still
need reference review even when a developer expects unchanged fields.
