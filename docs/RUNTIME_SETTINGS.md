# Runtime settings

Application environment variables use the `COILEM_` prefix. New project filenames
end in `.coilem`. Existing `.openem` files and lower-case schema keys remain compatible.

| Setting | Purpose |
| --- | --- |
| `COILEM_USER_DATA_ROOT` | Override durable motor-run storage and the solver cache. |
| `COILEM_SOLVE_WORKSPACE_MAX_BYTES` | Set the durable workspace budget; excludes the solver cache. |
| `COILEM_SOLVE_CACHE_MAX_BYTES` | Set the solver-cache byte budget used by rolling cleanup; defaults to 2 GiB. |
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
| `COILEM_BUILD_UI_DIST` | Package this prebuilt UI bundle in a wheel build instead of running `npm run build`. |
| `COILEM_BUILD_MAGNETO2D_BINARY` | Package this prebuilt Magneto2D executable in a wheel build instead of running Cargo. |
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
Python orchestration and shaft material selection also use fixed defaults instead
of inherited diagnostic switches. Gmsh initialization skips machine-local
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
