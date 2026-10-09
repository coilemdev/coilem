# Getting started: your first motor solve

This guide takes the included example motor from a clean checkout through
geometry review, mesh preparation, a local Magneto2D solve, and an immutable
report export.

The application in this guide is coilEM 0.2.0 and the bundled solver is
Magneto2D 0.3.2. coilEM requires Python 3.11 or newer, Node.js with npm, a Rust
toolchain with Cargo, and Git. The platform-specific commands below are setup
guidance, not a broad operating-system support guarantee. The exact system used
for the release-candidate walkthrough is recorded with the release evidence.

Use a stable Python release for preview validation. The public CI runtime
check uses Python 3.11 and the frontend check uses Node.js 24. See
[Validation](VALIDATION.md) for the remaining release checks and evidence scope.

## 1. Get the source

```powershell
git clone https://github.com/coilemdev/coilem.git
cd coilem
```

## 2. Install the backend

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On macOS or Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -e ".[dev]"
```

On Ubuntu/Debian, install `libglu1-mesa` before starting the backend:

```bash
sudo apt-get install libglu1-mesa
```

The locked requirements install the Python Gmsh package used by the public
native-mesh lane.

## 3. Build Magneto2D

From the repository root:

```text
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
```

This can take a few minutes on the first build. Later builds are incremental.
The backend can also build the binary on first use, but building now makes
toolchain errors easier to identify before a solve.

## 4. Start the local backend

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.public_main:app --host 127.0.0.1 --port 8000
```

On macOS or Linux:

```bash
.venv/bin/python -m uvicorn backend.public_main:app --host 127.0.0.1 --port 8000
```

Leave this terminal running. In another terminal, check the local service:

```text
curl http://127.0.0.1:8000/health
```

The response should include `"status":"ok"`, `"mode":"local"`, and
`"solver":"magneto2d"`.

The service is intentionally bound to loopback. It does not require a cloud
connection and is not exposed to other machines on the network.

## 5. Start the frontend

In a second terminal:

```text
cd frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Wait for the connection
indicator to show that the local backend is online before starting the solve.
Starting the frontend first is safe: it keeps retrying the loopback health check
and reconnects after the backend starts.

To run the non-motor workflow instead, choose **Magnetic field applications →
Cylindrical Halbach array**. Its Design stage starts with a 16-segment N42
example; review the ROI and leakage circles, continue to Solve, generate a mesh
preview, and run Magneto2D. The permanent finite-length limitation and all
Halbach exports are described in [Cylindrical Halbach array](HALBACH_ARRAY.md).

## 6. Load the example motor

On the landing page, select **Use Example Motor**.

The example is an 8-pole, 12-slot SPM motor using:

- a 200 mm stator outside diameter;
- a 100 mm stack length;
- single-layer concentrated windings;
- N42 permanent magnets;
- the bundled M350-50A nonlinear steel model;
- 30 A RMS phase current; and
- a 2,400 rpm rated speed.

The Design stage shows the parameter editor, geometry viewport, and design
health panel. For this first run, leave the example values unchanged. Review
the stator, rotor, winding, and material sections, then select
**Continue to Solve**.

Changing a dimension invalidates the old geometry and mesh. Wait for the
geometry to refresh before continuing.

### Choose sinusoidal or ideal six-step excitation

The Solve stage starts in **Sinusoidal** mode and shows three phase-shifted
sine traces in the run plan. To run the guided BLDC workflow, select
**Ideal six-step (120°)**. The run plan changes to stepped A/B/C traces so the
two conducting phases and one floating phase are visible before the solve.

For the release walkthrough, keep **Commutation advance** at `0` electrical
degrees and treat **Conducting phase current** as the terminal phase-current
plateau in amperes. **Phase connection: Wye (MVP)** is fixed. This is an ideal
current excitation: coilEM does not simulate PWM, current ripple, Hall timing,
dead time, startup, or ESC dynamics.

## 7. Prepare and inspect the mesh

The Solve stage begins preparing a mesh when it does not already have one.
You can also select **Prepare mesh** explicitly.

For the first run, keep the **Standard** solve plan:

- normal mesh density;
- corner refinement enabled;
- weighted-stress torque;
- Picard nonlinear iteration; and
- direct Cholesky linear solve.

When meshing completes, confirm:

- the geometry and mesh views match the intended motor;
- the mesh element count is non-zero;
- the minimum-quality row says **Pass**; and
- the solver gate reports no weak-element blocker.

If you change mesh density or refinement, select **Regenerate mesh** before
running the analysis.

## 8. Run the electromagnetic analysis

Select **Run analysis**. coilEM validates the configuration again and streams
progress while it:

1. generates the required per-angle Gmsh meshes;
2. runs Magneto2D at the requested positions;
3. computes torque, flux linkage, Back-EMF, and field outputs;
4. packages the public result; and
5. writes a durable run with reports and provenance.

Keep both terminals open until the solve finishes. **Cancel solve** requests a
clean stop and records the attempt as cancelled rather than publishing it as a
completed run.

If you only want a fast pipeline check, choose **Preview**. Preview does not
report an under-sampled THD value. Use **Standard** for the release walkthrough; it
reports Back-EMF THD and the H1-H12 spectrum. **High accuracy** is the UI name
for the `fine` preset; it uses a fine mesh and extends the spectrum through H24,
but it is not a separate launch benchmark requirement.

## 9. Review the result

After completion, select **View Results →** in the left footer, or **Results**
in the workflow header. **Run again** repeats the analysis; editing settings
restores **Run analysis** for the updated configuration. The Electromagnetic
performance page summarizes:

- average torque and torque ripple;
- returned A/B/C phase currents and all six commutation sectors for an ideal
  six-step run;
- fundamental Back-EMF;
- phase-neutral and line-to-line Back-EMF selection;
- peak tooth and yoke flux density;
- torque constant;
- Back-EMF THD and harmonic spectrum for Standard and High accuracy runs;
- solve time; and
- the exact material, operating point, solver, torque method, mesh, and rotor
  position provenance.

Use the plot tabs to inspect loaded torque, Back-EMF, harmonics when available,
and the field map. A dedicated cogging-torque result view is not part of this
preview. A plausible-looking plot is not by itself a validation result: check
units, operating point, mesh quality, angular sampling, and material assumptions
before using a result in a design decision.

## 10. Compare two saved runs

Open **Previous runs** after completing a second Magneto2D solve. Select one run
as the baseline and another as the candidate to compare their stored design,
operating-point, mesh, and headline result values. Comparison is descriptive:
it does not rerun either solver, establish cross-solver parity, or certify a
design.

The same dialog shows workspace usage and each run's size and status. Deleting
a run requires **Delete run** followed by **Delete permanently** for that exact
row. Completed runs are never pruned automatically, and a running solve cannot
be deleted there.

## 11. Export and preserve the report

The Saved locally section offers:

- **Download PDF** for a human-readable report with the motor's 2D cross-section
  and solved flux-density heatmap;
- **Download CSV** for long-form numerical data;
- **Open result folder** to reveal the durable run;
- **Save replayable run package** for the project, settings, evidence, and
  reports;
- **Open project** to restore the saved inputs; and
- **Rerun settings** to restore the inputs in the Solve stage.

Downloading an export serves the bytes created when the run completed. It does
not read unsaved form changes or rerun the solver.

The motor figures use the run's saved mesh and field data. The heatmap shows
the first loaded rotor position, with its angle and flux-density scale in
tesla. It is a snapshot of that position rather than the maximum over the
sweep. Runs without the required field data show an unavailable message.
Existing saved PDFs keep their original layout; new solves include the figures.

A completed run has this shape:

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

The default user-data root is:

- Windows: `%LOCALAPPDATA%\coilEM`
- macOS: `~/Library/Application Support/coilEM`
- Linux: `$XDG_DATA_HOME/coilem`, or `~/.local/share/coilem`

See [Local solve workspace](local_solve_workspace.md) for integrity, replay,
retention, cleanup, and `COILEM_USER_DATA_ROOT` override details.

## Optional command-line smoke test

The included smoke tool runs a real coarse Gmsh mesh and Magneto2D solve
through the same public FastAPI application:

On Windows:

```powershell
.\.venv\Scripts\python.exe tools\smoke_public_runtime.py
```

On macOS or Linux:

```bash
.venv/bin/python tools/smoke_public_runtime.py
```

This is a runtime check, not a replacement for reviewing the full application
report.

## Troubleshooting

### The frontend says the backend is offline

Confirm the backend terminal is still running and that
`http://127.0.0.1:8000/health` responds. Use the documented loopback host and
ports; the public browser client does not accept arbitrary API hosts.

### Cargo or Magneto2D cannot be found

Confirm `cargo --version`, then rerun the release build from the repository
root. The backend expects the binary built from
`solvers/magneto2d/Cargo.toml`.

### Gmsh is unavailable

Run the health check first, then confirm the active virtual environment can
import Gmsh:

```text
python -c "import gmsh; print(gmsh.__version__)"
```

Use the virtual environment's Python executable if `python` resolves to a
different installation.

### The mesh fails its quality gate

Return to Design and check the airgap, slot opening, tooth/yoke dimensions,
magnet width, and pole/slot combination. After changing geometry, regenerate
the mesh. Increasing mesh density cannot make physically invalid geometry
valid.

### The run cannot be published

coilEM refuses to publish incomplete evidence or exceed the configured solve
workspace limit. Open **Previous runs** from the error action, review the storage
meter, and explicitly delete an older completed run or retained incomplete
diagnostic that you no longer need. The meter and list refresh immediately;
then retry the analysis. coilEM never silently deletes a completed run.

## Model assumptions

The public motor UI uses WST torque and Direct Cholesky. Picard is the default
nonlinear solver; Newton is available in Advanced options as experimental
recovery when a run fails to converge. Importing a design with other torque or
linear-solver choices applies the public defaults and displays a notice.

The launch report is an electromagnetic 2D result. It does not include
supplier-specific core-loss prediction, temperature prediction,
demagnetization safety, or axial end effects. Review
[Materials](../MATERIALS.md) and [Magneto2D limitations](MAGNETO2D.md#limitations)
before using results outside an exploratory or validation workflow.

For known release limits, see [coilEM 0.2.0 release notes](../RELEASE_NOTES.md).
Use [GitHub Issues](https://github.com/coilemdev/coilem/issues) for public bugs
and [SECURITY.md](../SECURITY.md) for private vulnerability reporting.
