# Command line

The `coilem` command opens the app. Followed by a command, it works headless
for scripts, CI jobs and coding agents: it checks or solves a design file,
lists its saved run setups and describes every input. The commands use the
[Python client](PYTHON_CLIENT.md), so a design solves exactly as it does from
Python and through the app's `/solve` route.

```bash
coilem setups motor.coilem
```

```bash
coilem check motor.coilem --setup "High Speed"
```

```bash
coilem solve motor.coilem --setup "High Speed" --out result.json
```

```bash
coilem schema --out motor-schema.json
```

```bash
coilem version
```

`python -m coilem ...` is the same command, for environments whose scripts
folder is not on `PATH`. Bare `coilem`, its `--port`, `--no-browser` and
`--version` options, `coilem benchmark` and `coilem-serve` are unchanged.

## Commands

| Command | What it does | Solver work |
|---|---|---|
| `coilem check DESIGN` | Chooses the run setup, builds the request and runs the app's pre-solve checks; reports the effective settings and winding warnings | None: no mesh, no solve |
| `coilem solve DESIGN` | Solves the design and writes compact results | Yes |
| `coilem setups DESIGN` | Lists the design's saved run setups, which one is active, and whether each can be used | None |
| `coilem schema` | Describes every design input with its unit, limits and allowed values, the run-setup format, the output documents, exit codes and error codes | None |
| `coilem version` | The installed coilEM, its build, Python and platform | None |

`DESIGN` is a `.coilem` file saved by the app (schema 4) or a request JSON
that the Python client reads.

`check` and `solve` take the same settings:

| Option | Meaning |
|---|---|
| `--setup NAME` | Apply this saved run setup, by name (any case) or id. `--profile` is the same option. |
| `--analyses LIST` | Comma-separated analyses: `torque`, `back_emf`, `cogging`, `losses`, `thd`, `flux_density` |
| `--quality NAME` | `quick`, `standard`, `fine` or `custom` |
| `--mesh NAME` | `coarse`, `normal`, `fine` or `very_fine` |
| `--set NAME=VALUE` | Set any `solve_params` field, for example `--set current_amplitude_A=20`. VALUE is read as JSON when it parses (`20`, `true`, `null`), else as text. Repeat for more fields. |

`solve` also takes:

| Option | Meaning |
|---|---|
| `--server URL` | Solve in a running app (for example `http://127.0.0.1:2645`); the run joins its history, labelled with the setup |
| `--timeout SECONDS` | How long to wait for `--server` (default 3600) |
| `--fields` | Also keep the field pictures for the app's viewers (several MB) |
| `--progress MODE` | Progress on standard error: `text`, `json` (one JSON object per line), `none`, or `auto` (text on a terminal, none otherwise) |

Every command takes `--out PATH` (default: standard output), `--compact`
(JSON on one line) and `--quiet` (no messages on standard error, except
errors).

## Which settings are solved

1. With `--setup`, that saved setup applied to the design's saved settings, as
   the app's setup picker applies it. An operating-only setup leaves the
   design's accuracy, mesh and solver settings alone. A setup that is missing,
   unreadable, made for another reference model or current-angle
   convention, or that solves with Elmer is refused before anything is
   solved.
2. Without it, the design's saved settings, as the app solves a reopened
   design file. When the design's active setup still describes them, the run
   is labelled with it; when they were edited after the setup was chosen, the
   saved settings are still solved and a note says so.

`--analyses`, `--quality`, `--mesh` and `--set` apply on top. When they change
the setup, the output still names it, with `modified: true` and no
`run_setup` label. Both `check` and `solve` report this in `setup` and the
resulting `effective` settings.

## Output

Standard output (or `--out`) receives exactly one JSON document; progress and
messages go to standard error. Every document has:

- `schema`: `coilem.cli.check/v1`, `coilem.cli.solve/v1`,
  `coilem.cli.setups/v1`, `coilem.cli.schema/v1`, `coilem.cli.version/v1`, or
  `coilem.cli.error/v1` when the command failed;
- `ok`, `command` and `coilem_version`.

A `solve` document holds:

- `solver`: `in_process` or `server`;
- `design`: its path and name;
- `setup`: the source, the setup's id, version, name and kind, `modified`,
  the `run_setup` label and notes;
- `effective`: the solved `solve_params`, `solve_options` and
  `torque_speed_analysis`;
- `warnings`;
- `metrics`: the headline numbers;
- `request`: the exact request solved;
- `result`: the app's result without the field pictures.

Units are in the names (`_Nm`, `_V`, `_A`, `_Wb`, `_H`, `_s`, ...), as in the
app's results. A quantity the run did not compute is `null`,
never 0, and the result keeps each output's status and reason as the app
reports them. Read the file back in Python with
`coilem.Result.load("result.json")`.

## Errors and exit codes

A failed command writes a `coilem.cli.error/v1` document to the same place
(standard output, or `--out` when it can be written). The document has
`exit_code` and an `error` with these fields:

- `error_code` and `message`;
- `field`: the input at fault, such as `setup`, `solve_params.current_amplitude_A` or `design`;
- `suggestion`, when there is one;
- `problems`, for input errors.

It also prints the message on standard error.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Unexpected internal error (set `COILEM_DEBUG=1` for a traceback) |
| 2 | Invalid command line; usage on standard error, no document |
| 3 | Invalid input: design file, run setup, settings or `--out` path. Nothing was solved. |
| 4 | The solve started but failed: solver, convergence, timeout, or no app at `--server` |
| 130 | Cancelled with Ctrl+C, Ctrl+Break (Windows) or SIGTERM. The solve's worker processes are stopped. |

`coilem schema` lists every `error_code` with its meaning. Common ones:

- `SETUP_NOT_FOUND`, `SETUP_UNREADABLE`, `SETUP_INCOMPATIBLE`,
  `SETUP_SOLVER_UNAVAILABLE`;
- `DESIGN_FILE_UNREADABLE`, `DESIGN_SCHEMA_UNSUPPORTED`;
- `INVALID_INPUT`, `OUTSIDE_SOLVE_BOUNDARY`;
- `NONLINEAR_CONVERGENCE_FAILED`, `SOLVER_FAILED`, `SOLVER_CANCELLED`,
  `SERVER_UNREACHABLE`.

## For coding agents

- Run `coilem schema` once to learn the inputs, their units and limits, and
  the documents and codes above.
- Run `coilem setups DESIGN` to find setup names, then `coilem check DESIGN`
  with the same options before `coilem solve`. `check` does no solver work.
- Branch on the exit code and `error.error_code`, not on message text.
- Read results from `metrics` and `result`. Treat `null` as not computed.
- Run one solve at a time per machine: each solve already uses every core.

## Windows

The command starts its solver worker processes safely. A Python script that
calls `coilem.solve` must do so from under `if __name__ == "__main__":`; see
[Scripts and worker processes](PYTHON_CLIENT.md#scripts-and-worker-processes).
Ctrl+Break, or `CTRL_BREAK_EVENT` sent to a process started with
`CREATE_NEW_PROCESS_GROUP`, cancels a solve like Ctrl+C.
