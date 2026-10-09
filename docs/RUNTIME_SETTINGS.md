# Runtime settings

Application environment variables use the `COILEM_` prefix. New project filenames
end in `.coilem`. Existing `.openem` files and lower-case schema keys remain compatible.

| Setting | Purpose |
| --- | --- |
| `COILEM_USER_DATA_ROOT` | Override the local solve storage directory. |
| `COILEM_SOLVE_WORKSPACE_MAX_BYTES` | Set the workspace storage budget. |
| `COILEM_LOCAL_API_PORT` | Select the loopback port when using the `coilem-serve` entry point. |
| `VITE_COILEM_LOCAL_API_BASE` | Select a loopback backend URL for the frontend build/dev server. |
| `COILEM_LOCAL_UI_ORIGIN` | Allow one additional HTTP loopback UI origin with an explicit port. |
| `COILEM_ENABLE_ELMER` | Enable the optional external Elmer development lane when set to `1`. |
| `COILEM_BUILD_COMMIT` | Supply the application build identity. |
| `COILEM_TEST_PYTHON` | Select the Python interpreter for browser tests. |

## Native solve isolation

The public application's motor, teaching and Halbach processes inherit only
`PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `TMPDIR`, `LANG`, `LC_ALL` and
`TZ`. Runtime library injection variables and arbitrary shell variables are
excluded. Numerical options are generated from the request; setting a native
solver debug variable in your shell does not change an application solve.
Python orchestration and shaft material selection also use fixed defaults instead
of inherited diagnostic switches. Gmsh initialization skips machine-local
configuration files; mesh options come from the application and request. Build-tool discovery is separate from solver execution.

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
