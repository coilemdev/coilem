# Local solve workspace

coilEM stores completed public solves separately from its disposable solver
cache. The default root follows the host operating system:

- macOS: `~/Library/Application Support/coilEM`
- Windows: `%LOCALAPPDATA%\coilEM`
- Linux: `$XDG_DATA_HOME/coilem`, or `~/.local/share/coilem`

`COILEM_USER_DATA_ROOT` may override the root for a portable installation or
test environment. The application creates:

```text
solves/
  <project>/
    <run-id>/
      manifest.json
      project.openem
      request.json
      result.json
      material.json
      artifacts/
      report/
        summary.json
        report.pdf
        report.csv
        run-package.zip
```

Every run ID is collision-safe. A run is first written to a sibling
`.partial` directory. Only after the project, resolved request, material
record, sanitized result, reports, retained artifacts, and final manifest are
durable is that directory atomically renamed to its public run ID. Failed and
cancelled attempts keep a partial manifest with safe diagnostics and never
appear as completed evidence.

The manifest hashes the project, request/settings, material record and curve
identity, result, solver version, and application commit. Loading a run reports
integrity separately and always treats the stored result as immutable historical
evidence. “Open project” and “Rerun settings” restore inputs only; the user must
explicitly start a new solve.

PDF, CSV, and replay-package downloads are generated once from those stored
files before the run is published. Downloading after an application restart
serves the same bytes and never reads unsaved form state or starts a solver.
The replay package contains the manifest, `.openem` project, resolved request,
material contract, result, report exports, and retained artifacts. Missing or
tampered exports fail their integrity check; an older manifest directs the user
to reopen its project and explicitly create a current run.

## Retention

Durable runs are user-owned and are not silently deleted. The workspace has a
10 GiB default hard limit, configurable with
`COILEM_SOLVE_WORKSPACE_MAX_BYTES`. It refuses a new run when already full and
does not publish a completed run that would cross the limit. The run-list API
reports used and available bytes so cleanup can be explicit. The manifest also
recommends keeping the latest 25 runs per project. The delete API requires the
caller to repeat the exact run ID and refuses paths outside the configured
root.

The **Previous runs** dialog shows the workspace total and the size and status
of each saved, failed, or cancelled run. Deletion is always a two-step explicit
action for one run. A running solve cannot be deleted from the dialog. When the
workspace is full, the solve error opens this dialog so the user can remove an
older completed run or retained incomplete diagnostic and retry without finding
the data directory manually. The refreshed storage total is returned after
deletion. coilEM never silently prunes a completed run.

The separate `solve_cache` contains disposable meshing and field-solve
intermediates. Its rolling cleanup policy does not remove durable run files.
Heavy artifacts referenced by a completed public result are copied into that
run and addressed by root-confined opaque IDs, so clearing the cache does not
break an archived run.

Field playback intentionally retains one exact numerical snapshot and one
1536px layered raster set per solved position. This makes stopped-frame zoom,
probing, and density controls truthful at every angle, but it also makes field
playback the dominant per-run storage cost and causes the configured workspace
limit to be reached sooner than summary-only runs.
