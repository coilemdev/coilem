# Local solve workspace

coilEM stores completed public motor solves and its disposable solver cache under
one user-data root. The default root follows the host operating system:

- macOS: `~/Library/Application Support/coilEM`
- Windows: `%LOCALAPPDATA%\coilEM`
- Linux: `$XDG_DATA_HOME/coilem`, or `~/.local/share/coilem`

`COILEM_USER_DATA_ROOT` may override the root for a portable installation or
test environment. This override moves both durable runs and the solver cache
described below. The application creates:

```text
launcher.lock        # held by the running `coilem` launcher
launcher.json        # its port, process ID and version, while it runs
solve_cache/
  magneto2d-<timestamp>/
solves/
  <project>/
    <run-id>/
      manifest.json
      project.coilem
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
The replay package contains the manifest, `.coilem` project, resolved request,
material contract, result, report exports, and retained artifacts. Missing or
tampered exports fail their integrity check; an older manifest directs the user
to reopen its project and explicitly create a current run.
Existing runs containing `project.openem` remain readable and retain their
original export bytes.

Halbach workspaces keep design drafts locally in the browser and support
design-file save/reopen. Their solved reports stay in the current browser
session and are not published to this motor-run workspace. Cylindrical
Halbach exports are generated separately from the report.

## Retention

Durable runs are user-owned and are not silently deleted. The one part coilEM
removes on its own is field playback, the frames and images behind the Results
field view, which is most of a run's size. Each design (project) keeps it for
its newest 5 completed runs, configurable with
`COILEM_FIELD_PLAYBACK_KEEP_RUNS`. Older runs keep their manifest, project,
request, result, material record and reports, and stay comparable and
exportable. The manifest keeps each removed artifact's path and hash, marked
`removed_at`, and records `retention.field_playback_removed_at`. The
integrity check skips those artifacts, and **Manage previous runs** marks the run
"field playback removed".

The workspace has a 10 GiB default hard limit, configurable with
`COILEM_SOLVE_WORKSPACE_MAX_BYTES`. When it is full, coilEM first removes field
playback from the oldest runs, keeping each design's newest run whole. It
refuses a new run only if the workspace is still full, and does not publish a
completed run that would cross the limit. The run-list API
reports used and available bytes so cleanup can be explicit. The manifest also
recommends keeping the latest 25 runs per project. The delete API requires the
caller to repeat the exact run ID and refuses paths outside the configured
root.

**Manage previous runs** opens a dialog showing the workspace total and the size and status
of each saved, failed, or cancelled run. Deletion is always a two-step explicit
action for one run. A running solve cannot be deleted from the dialog. When the
workspace is full, the solve error offers **Manage previous runs** so the user
can open this dialog and remove an
older completed run or retained incomplete diagnostic and retry without finding
the data directory manually. The refreshed storage total is returned after
deletion. coilEM never silently deletes a completed run.

The solver cache contains disposable meshing and field-solve intermediates in
`solve_cache/` under the same root. The durable workspace's 10 GiB budget does
not cover it, and it is excluded from the storage meter. Before creating a new
`magneto2d-*` directory, cleanup keeps at most the ten newest existing matching
directories whose combined size fits `COILEM_SOLVE_CACHE_MAX_BYTES` (2 GiB by
default). The newest existing directory is always kept, because a failed or
cancelled solve restores the previous result, and the new run can exceed the
budget until the next cleanup. Its rolling cleanup does not remove durable run
files. Earlier releases wrote this cache to `~/.openem/solve_cache`; coilEM no
longer uses that directory, and it can be deleted.
Heavy artifacts referenced by a completed public result are stored in that run
and addressed by root-confined opaque IDs, so clearing the cache does not break
an archived run. They are hard links to the cache's files where the volume
allows it, and copies otherwise. Cache files are written once and only deleted,
so pruning the cache removes only its own name for them.

Field playback intentionally retains one numerical snapshot and one 1536px
layered raster set per solved position. This makes stopped-frame zoom, probing,
and density controls truthful at every angle, but it also makes field playback
the dominant per-run storage cost. The solve reads its physics from the cache's
gzipped-JSON frames. A saved run keeps each frame's compact copy (`.f32.xz`)
instead: real-valued arrays as float32 (about seven significant digits),
integers, strings and scalars exact, xz-compressed. That is a quarter to a
third of the gzipped JSON. Runs saved by earlier releases keep their `.json.gz` frames,
and both forms read back the same way.
