# Qualification collection

The release benchmark workflow builds Magneto2D once on each selected platform,
then measures eight balanced A–D groups and four Prius groups concurrently.
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

Use dispatch input `reuse_run` with the original collection run ID and its exact
measured candidate SHA to rebuild the joins without any field solves. The
workflow uses its own current download tooling while grading with the frozen
candidate's backend. This also recovers legacy artifacts that bundled large
raw archives with compact inputs. Downloads are staged one shard at a time;
redundant temporary archive copies are removed before the next download, while
the originals remain on the server. Prius retained inputs are verified and linked
into the join without a second physical copy.

If a shard times out, dispatch with `source_run` and a `retry_shards` JSON array
of `platform/shard` IDs. Repairs download the original binary and require the
same candidate and execution identity. Native jobs use verified resume;
Prius jobs preserve verified completed cases and collect only missing cases
through the frozen candidate's own collector. The derived registration records
the parent and case hashes. Failed attempts remain in raw artifacts. Finish
with a join-only dispatch using `reuse_run` plus `supplement_runs` (a JSON array
of repair-run IDs); every original request and result keeps its measured bytes.

## Disk and retention

Keep output outside the checkout. A–D jobs use `--archive-runtime`: every raw
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

## PR evidence gate

`python -m tools.physics_impact --base <base-sha>` compares the union of the old
and new source registries, including the Prius-specific sources. Removing a
registry entry cannot hide a changed source. Changes to registered suite or
reference contracts also require evidence. A physics PR passes only when the
strict release check accepts its current-tree Windows, macOS and Prius reports.
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

The public qualification basis and report path follow the primary registered
record. The release gate still requires actual matching Windows/macOS/Prius
measurements; changing hashes alone cannot qualify a build. A weekly workflow
compares fresh measurements and opens one issue for unexplained drift.

Item 4 of #194 is deliberately excluded: the physics source registry remains
unchanged, no solver modules are split, and dependency identity/fingerprints
are not introduced here. Changed configuration/model code may therefore still
need reference review even when a developer expects unchanged fields.
