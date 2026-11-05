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
queue time and platform concurrency limits can affect it.

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
workflow dispatch. Make `qualification evidence required` a required status
check on `main` and `release/v0.5.1`, enable required code-owner review, and
protect the qualification rules listed in `.github/CODEOWNERS`. Merely committing
a workflow or CODEOWNERS file cannot enable those repository settings.
