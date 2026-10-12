# coilEM 0.2.0 Developer Preview

coilEM 0.2.0 is a source-built developer preview of the local motor-design
application. It bundles Magneto2D 0.3.2 as its field solver; the application
and solver use separate version numbers.

## Packaged launcher (unreleased)

The source-built `coilem` launcher serves the UI and API together at
`http://127.0.0.1:2645` by default. Halbach autosaves and tutorial progress
saved in the browser under the development origin on port 5173 do not appear
at the packaged origin. Browser-saved state also stays with its original port
when the launcher falls back to another port. Saved motor runs remain in the
user-data folder.

## Design file loading (unreleased)

Bundled examples and design files that leave out the tooth-shoe settings now
load without tooth shoes, as the backend reads them. They used to inherit the
starter motor's shoes: the SPM 24p example then failed geometry validation,
and the two IPM examples solved with narrower slot mouths than their files
define. Saved runs keep the geometry they were solved with.

## Faster solves (unreleased)

Magneto2D spent about 2 s per rotor position finding the airgap radii it
samples torque and fields on. It now indexes the airgap triangles, so a
position's solver process takes about a quarter of the time with identical
results. A Standard run of the IPM 14p example took 146 s instead of 236 s,
and the SPM 8p/12s example 106 s instead of 140 s.

The work after the field sweep is also faster. Field-line frames skip
triangles a contour level cannot cross and are written with the fast JSON
encoder and light gzip. Playback images render in worker processes. The
run package stores already-compressed files instead of deflating them again,
and the steel flux-density summary is gathered while frames are built
instead of re-reading every frame. With both changes the IPM 14p run took
98 s and the SPM 8p/12s run 61 s. Frame and image files are about 10%
larger. Results are unchanged; the steel RMS flux densities can differ in
the 14th significant digit because their sums are added in a different order.

The bookkeeping around each rotor position's solve no longer queues behind
Python's global lock. Meshes are written for the solver as compact JSON,
reports are saved without being re-serialized, the no-load copy of each mesh
shares its arrays, copies use a faster method, and mesh-evidence hashes skip
a per-value walk and reuse the mesh's serialized text. Hashes and results are
unchanged. The IPM 14p run then took 76 s and the SPM 8p/12s run 48 s.

Windows now generates independent Gmsh meshes in worker processes, with up
to eight workers limited by the host CPU count. Playback sweeps with at least
eight frames also use up to eight worker processes to render and encode the
same image layers. Field-frame extraction also uses up to eight processes,
limited by CPU, solve-worker and frame counts. All pools use Windows spawning.
Frames and steel RMS contributions retain their angle order. Cancelling a solve
skips queued meshes and frames, lets running work finish, and joins workers
before releasing the solve lane.

Installed applications can disable mesh, field-frame and playback pools with their
individual `COILEM_MAGNETO2D_ALLOW_*_PROCESS_POOL` switches, or disable all Python
pools with `COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL=0` before restarting. These
disable-only compatibility controls keep numerical settings isolated and are
not forwarded to Magneto2D.

## Solver time (unreleased)

The Solver time on the Results page and in the PDF and CSV reports is now the
wall-clock time of meshing, solving and building the result. It used to add up
every rotor position's solver time, although positions run in parallel, so a
4-minute IPM 14p run reported over 20 minutes. Saved results keep that sum as
solver CPU time. Runs saved before this change still show the summed value.

## Field solution position slider (unreleased)

Moving the Position slider on a solved field no longer freezes the page for
seconds at each position. The slider shows each position's playback image
straight away and loads the exact solver frame once it stops. Preparing that
frame now takes about 0.15 s, down from about 2 s for each of the Resultant
and PM-only fields. Fast scrubbing also no longer crashes the viewer with a
"detached" image error.

Playback no longer stalls at higher speeds. Above about 30 new frames per
second, playback shows every second or third solved position, and a loop of
up to 16 frames stays in memory after its first pass.

## Cancel a stator-only field (unreleased)

A running **Stator only** field can now be canceled from the run button,
which reads **Cancel stator field** while it runs, or from the field view's
progress overlay. The resultant field stays available. Before, the run held
the solver until it finished, blocking any other solve.

## Mesh view zoom and pan (unreleased)

Zooming or panning the Mesh tab now redraws in about 45 ms instead of about a
second for the 29k-element example mesh. The Halbach mesh views draw their
meshes the same faster way.

## Qualification

Numerical qualification for this preview is the published [A/B/C/D benchmark
report v1.1](benchmarks/main-20261009-bad71d9/benchmark_report.md). It compares
Magneto2D with fresh, matched FEMM references across 30 fixtures: 27 PASS,
2 FAIL and 1 unsupported. See [Validation](docs/VALIDATION.md#qualification-status)
for the gates and limits.

- **Qualified:** these tested combinations, each with every v1.1 fixture
  passing, using M350-50A steel, native Gmsh meshing and local Magneto2D:
  - SPM with single-layer concentrated windings, under sinusoidal current
    (Phase A) or ideal six-step excitation (Phase D);
  - SPM with two-layer distributed windings, full pitch or 5/6 short pitch,
    under sinusoidal current (Phase C); and
  - flat-buried IPM with single-layer concentrated windings, under sinusoidal
    current (Phase B).
- **Experimental:**
  - V-shape IPM (two of six fixtures fail);
  - accepted combinations the benchmark did not measure: six-step with
    distributed windings, single-layer distributed windings, and IPM with
    distributed windings; and
  - Halbach, tutorial and generic-field workflows.
- **Unsupported:** multi-layer IPM rotors such as the Prius 2004 fixture.

The app shows the current design's status, with its reason, in Design health
and on the Solve and Results pages, and saved runs record it in their PDF and
CSV reports.

The guided SPM path includes both balanced sinusoidal current and ideal
wye-connected 120-degree six-step excitation. Six-step runs preserve exact
commanded phase currents on the torque grid, show the six commutation sectors,
and export phase-neutral and line-to-line Back-EMF with the excitation identity.

The preview includes:

- geometry and native-mesh review;
- Preview, Standard, and High accuracy (`fine`) solve plans;
- loaded torque, Back-EMF, field playback, and material/solver provenance;
- Back-EMF THD and H1-H12 spectrum for Standard, extended through H24 for
  High accuracy; Preview intentionally omits an under-sampled THD value;
- immutable local runs with PDF, CSV, and replay-package exports;
- explicit storage usage and confirmed deletion of one saved or incomplete
  run;
- descriptive comparison of two saved Magneto2D runs; and
- visually distinct sinusoidal and six-step run-plan previews, plus aligned
  torque/current results for the guided ideal six-step workflow.

Experimental non-motor workflows include solver-backed lessons and cylindrical
and linear Halbach arrays. Halbach workspaces save/reopen design files and show
reports in the current browser session. Cylindrical arrays additionally export
report/problem/field JSON, sample CSV, design SVG/PNG, and PDF. These workflows
are separate from motor saved-run history; the linear UI currently has no
report downloads. See [Halbach arrays](docs/HALBACH_ARRAY.md).

## Reliability and reporting updates

- Completed Solve workflows lead with **View Results**, while retaining
  access to run the analysis again and return to Design.
- Newly generated saved-run PDFs include the motor's 2D geometry and a stored
  solved flux-density heatmap. Existing immutable reports retain their
  original content.
- Narrow windows retain access to solve progress and completed reports, with
  a visible **View Results** action.
- A failed geometry preview recovers after the local backend reconnects,
  preserving the latest draft. **Retry geometry preview** is also available.
- Timing labels separate the estimated run time, solver timing, and total
  elapsed time through playback preparation and saving. Total elapsed is
  measured during the current session and is absent from older or reopened
  results.
- The Solve page estimates the whole run as a range, such as "about 2–4 min",
  from the prepared mesh and the meshes and positions the solver will run. It
  includes meshing and saving, and replaces a flat cost per rotor position
  that missed IPM and larger runs by up to 2.4 times.
- Reports identify the requested torque method and the method actually used;
  missing provenance is shown as not recorded.
- The public motor permanent-magnet catalog agrees with the bundled native
  motor solver inputs; Halbach and Elmer use a separate legacy table described
  in [Materials](MATERIALS.md).
- Public CI builds and checks the exported source using locked runtime dependencies; development tools and the Rust toolchain are not fully pinned.

## Known limitations

- This is a source build. There is no installer, code signing, notarization,
  auto-update mechanism, or bundled Python runtime.
- No broad Windows, macOS, or Linux support matrix is claimed. The exact system
  used for the release-candidate walkthrough must be recorded with its evidence;
  reports from other systems are welcome.
- Qualification is agreement with FEMM, a reference 2D finite-element solver,
  on the measured fixtures. It is not a hardware measurement or an engineering
  certification, and it does not cover cogging, THD, airgap harmonics, losses
  or thermal behavior. V-shape IPM, Halbach, tutorial, and generic-field
  surfaces are experimental.
- A dedicated cogging-torque results view is not included.
- Compare is descriptive; it is not cross-solver parity, statistical
  validation, or an engineering certification.
- Elmer is disabled, hidden, and not probed in the release environment. Setting
  `COILEM_ENABLE_ELMER=1` enables a development/testing adapter and does not
  expand the release claim.
- FEMM, thermal analysis, hosted services, accounts, telemetry, cloud storage,
  and supplier-specific core-loss prediction are excluded.
- Six-step support is an ideal current-commanded model for the guided
  inner-rotor, wye-connected SPM example. PWM, switching/current ripple, Hall
  timing, dead time, startup, delta windings, outer-rotor/outrunner geometry,
  and dynamic ESC behavior are excluded.
- Results are 2D electromagnetic estimates. They do not establish thermal,
  demagnetization, structural, acoustic, manufacturing, or safety suitability.

## Data and support

Completed and incomplete run records are user-owned and are never silently
deleted. Use **Manage previous runs** to inspect storage and explicitly delete one run
when the workspace is full. Reopening or comparing a run never starts a solver.

Use [GitHub Issues](https://github.com/coilemdev/coilem/issues) for reproducible
bugs and usage questions. Report security vulnerabilities privately as
described in [SECURITY.md](SECURITY.md).
