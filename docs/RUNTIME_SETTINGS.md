# Runtime settings

Application environment variables use the `COILEM_` prefix. New project filenames
end in `.coilem`. Existing `.openem` files and lower-case schema keys remain compatible.

| Setting | Purpose |
| --- | --- |
| `COILEM_USER_DATA_ROOT` | Override durable motor-run storage and the solver cache. |
| `COILEM_SOLVE_WORKSPACE_MAX_BYTES` | Set the durable workspace budget; excludes the solver cache. |
| `COILEM_SOLVE_CACHE_MAX_BYTES` | Set the solver-cache byte budget used by rolling cleanup; defaults to 2 GiB. |
| `COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL` | Set to `0` to generate Gmsh meshes in the backend process; works in the installed app. |
| `COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL` | Set to `0` to use threads for playback rendering; works in the installed app. |
| `COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL` | Set to `0` to extract field frames with one backend worker; works in the installed app. |
| `COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL` | Set to `0` to disable all Python process pools; works in the installed app. |
| `COILEM_LOCAL_API_PORT` | Select the loopback port for `coilem-serve`, or an exact port for the `coilem` launcher. |
| `VITE_COILEM_LOCAL_API_BASE` | Select a loopback backend URL for the Vite development server; production bundles call their own origin. |
| `COILEM_LOCAL_UI_ORIGIN` | Allow one additional HTTP loopback UI origin with an explicit port. |
| `COILEM_ENABLE_ELMER` | Enable the optional external Elmer development lane when set to `1`. |
| `COILEM_ELMER_HOME` | Pin Elmer discovery to an installation root or executable directory. |
| `COILEM_ELMER_RETAIN_ARTIFACTS` | Retain successful raw Elmer cases for diagnostics when set to `1`. |
| `COILEM_ELMER_RUN_ROOT` | Override the raw Elmer case directory, which has rolling retention. |
| `COILEM_ELMER_ANGLE_WORKERS` | Set development-lane parallel positions; positive integer, capped at 16. |
| `COILEM_ELMER_ALLOW_UNQUALIFIED` | Bypass Elmer version qualification for development diagnostics when set to `1`; see [Elmer](ELMER.md). |
| `COILEM_BUILD_COMMIT` | Supply the application build identity; set at wheel build time, it is also stamped into the package. |
| `COILEM_TEST_PYTHON` | Select the Python interpreter for browser tests. |
| `COILEM_MAGNETO2D_BINARY` | Run this Magneto2D executable instead of the packaged or source-built one. |
| `COILEM_MAGNETO2D_BUILD_RUSTFLAGS` | Override Rust flags used when the backend builds Magneto2D. |
| `COILEM_BUILD_UI_DIST` | Package this prebuilt UI bundle, with its `.build.json` record, instead of running `npm run build`; see [Release wheels](RELEASING.md). |
| `COILEM_BUILD_MAGNETO2D_BINARY` | Package this prebuilt Magneto2D executable, with its `.build.json` record and crate licenses, instead of running Cargo. |
| `COILEM_WHEEL_PLATFORM_TAG` | Set the wheel platform tag from the release policy. |
| `COILEM_VERSION_SUFFIX` | Append a `.devN` suffix to the package version for a TestPyPI rehearsal. |
| `CARGO` | Select the Cargo executable for backend build-tool discovery. |

The separate cache path and retention policy are documented in
[Local solve workspace](local_solve_workspace.md#retention).

## The `coilem` launcher

An installed package (`pip install .` from a checkout, which still needs Node.js
and Cargo to build) provides `coilem`. It serves the built UI and the API from
one loopback process and opens the browser at `http://127.0.0.1:<port>`,
never `localhost`. Browser-saved state, such as Halbach autosaves and tutorial
progress, belongs to that exact origin, so state saved under the development
UI at port 5173 does not appear there. Use `--no-browser` to skip opening a
browser window.

- `--port N` and `COILEM_LOCAL_API_PORT` use exactly that port and stop with an
  error when it is occupied.
- Otherwise the launcher uses port 2645. If another program holds it, the
  launcher falls back to the next free port in 2645–2654, warns that
  browser-saved state is unavailable there, and does not remember the
  fallback. On Windows, a port in a Hyper-V or WSL excluded range counts as
  occupied.
- One server runs per user-data root. A second launch with the same root opens
  the browser at the running server and exits, provided any explicitly requested
  port matches the running server. A different exact port fails with an error;
  stop the running copy or use another `COILEM_USER_DATA_ROOT` to change ports.
  If a different coilEM version is running there, the launcher prints both
  versions and exits.
- Ctrl+C stops accepting work and cancels active motor, Halbach and lesson
  solver processes. An in-flight motor run stays recorded as cancelled. A
  second Ctrl+C forces exit.

The development workflow is unchanged: `coilem-serve` and the documented
`uvicorn` command serve only the API on port 8000, and the Vite development
server sends requests to `VITE_COILEM_LOCAL_API_BASE`.

The packaged binary is resolved before a source build: `COILEM_MAGNETO2D_BINARY`
first, then the executable shipped in the package, then, only in a source
checkout, a Cargo release build. Native solver processes run in temporary or
run-artifact directories, never in the installation or source tree.

## Native solve isolation

The public application's Magneto2D processes for motor, teaching and Halbach
solves inherit only
`PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `TMPDIR`, `LANG`, `LC_ALL` and
`TZ`. Runtime library injection variables and arbitrary shell variables are
excluded. Numerical options are generated from the request; setting a native
solver debug variable in your shell does not change an application solve.
Python orchestration uses fixed defaults except for the four disable-only
process-pool compatibility controls below. Shaft material selection and
numerical diagnostic switches remain isolated. Gmsh initialization skips machine-local
configuration files; mesh options come from the application and request. Build-tool discovery is separate from solver execution.

The optional Elmer development lane does not use this environment allowlist:
its processes inherit the parent environment, with additional runtime-path
setup on Windows. Do not apply the Magneto2D isolation guarantee to Elmer.

New motor results include `solve_metadata.solver_environment`, with policy
`request-only-v1` and explicit native options. Raw motor input/report artifacts
retain the same policy. Options absent from that record use defaults in the
recorded solver version. Operating-system paths and arbitrary environment
contents are never copied into this record. Older cached results leave this
field empty; they are not retroactively labelled isolated.

Direct use of the Magneto2D CLI is a separate research interface. It still
accepts the documented `COILEM_*` and `MAGNETO2D_*` diagnostic switches; results
from custom CLI environments are not equivalent to the application's fixed
policy. Document those settings when sharing direct-CLI experiments.

## Process-pool compatibility fallback

If Python worker processes cannot start on a machine, stop the running backend
or installed app first, then disable its process pools before restarting. In
Windows PowerShell, for an installed app:

```powershell
$env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL = "0"
coilem
```

For a source checkout, use the same setting before the usual backend command:

```powershell
$env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL = "0"
.\.venv\Scripts\python.exe -m uvicorn backend.public_main:app --host 127.0.0.1 --port 8000
```

Gmsh then generates meshes in the backend process, playback uses threads, and
field-frame production uses one worker. The mesh runtime estimate follows the
serial worker count. To disable only one pool, set its specific variable above
to `0` and leave the shared variable unset. The shared off switch takes priority
over the specific switches in the installed application.

These isolated-runtime controls accept `0`, `false`, `no` or `off`, ignoring
case and surrounding spaces. Other values preserve the approved defaults;
`1` cannot force on a disabled pool or enable diagnostic numerical settings.
The controls stay in Python and are not passed to Magneto2D. To restore the
defaults, remove any off switches and restart the app; for the shared switch:

```powershell
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL -ErrorAction SilentlyContinue
```

Restarting is required because a second `coilem` launch reuses an existing
server in the same user-data folder. Settings in a new shell do not change that
server. This fallback changes concurrency, while retaining the same numerical
options, meshes and renderer.

Without an off switch, field-frame extraction uses up to eight processes,
capped by CPU count, solve concurrency and frame count. Windows workers use
`spawn`. Frames and steel RMS partials are collected by angle index and reduced
in that fixed order. Cancellation skips queued frame work and joins workers
before the solve lane is released.
