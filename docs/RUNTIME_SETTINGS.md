# Runtime settings

Application environment variables use the `COILEM_` prefix. New project filenames
end in `.coilem`. Existing `.openem` files and lower-case schema keys remain compatible.

| Setting | Purpose |
| --- | --- |
| `COILEM_USER_DATA_ROOT` | Override durable motor-run storage and the solver cache. |
| `COILEM_SOLVE_WORKSPACE_MAX_BYTES` | Set the durable workspace budget; excludes the solver cache. |
| `COILEM_SOLVE_CACHE_MAX_BYTES` | Set the solver-cache byte budget used by rolling cleanup; defaults to 2 GiB. |
| `COILEM_LOCAL_API_PORT` | Select the loopback port when using the `coilem-serve` entry point. |
| `VITE_COILEM_LOCAL_API_BASE` | Select a loopback backend URL for the frontend build/dev server. |
| `COILEM_LOCAL_UI_ORIGIN` | Allow one additional HTTP loopback UI origin with an explicit port. |
| `COILEM_ENABLE_ELMER` | Enable the optional external Elmer development lane when set to `1`. |
| `COILEM_ELMER_HOME` | Pin Elmer discovery to an installation root or executable directory. |
| `COILEM_ELMER_RETAIN_ARTIFACTS` | Retain successful raw Elmer cases for diagnostics when set to `1`. |
| `COILEM_ELMER_RUN_ROOT` | Override the raw Elmer case directory, which has rolling retention. |
| `COILEM_ELMER_ANGLE_WORKERS` | Set development-lane parallel positions; positive integer, capped at 16. |
| `COILEM_ELMER_ALLOW_UNQUALIFIED` | Bypass Elmer version qualification for development diagnostics when set to `1`; see [Elmer](ELMER.md). |
| `COILEM_BUILD_COMMIT` | Supply the application build identity. |
| `COILEM_TEST_PYTHON` | Select the Python interpreter for browser tests. |
| `COILEM_MAGNETO2D_BUILD_RUSTFLAGS` | Override Rust flags used when the backend builds Magneto2D. |
| `CARGO` | Select the Cargo executable for backend build-tool discovery. |

The separate cache path and retention policy are documented in
[Local solve workspace](local_solve_workspace.md#retention).

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
