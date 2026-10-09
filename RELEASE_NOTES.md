# coilEM 0.2.0 Developer Preview

coilEM 0.2.0 is a source-built developer preview of the local motor-design
application. It bundles Magneto2D 0.3.2 as its field solver; the application
and solver use separate version numbers.

## Proposed qualification path

This is the proposed release scope. Publication and exact-candidate numerical
and interactive signoff remain pending; see [Validation](docs/VALIDATION.md).

The qualification target is the included 8-pole/12-slot radial-flux SPM example
with M350-50A steel, native Gmsh meshing, the Standard solve plan, and local
Magneto2D execution. Numerical qualification remains pending; no motor path is
yet release-qualified. Other configurations accepted by the runtime are
experimental capabilities.

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
- Timing labels separate approximate solver estimates, solver timing, and
  total elapsed time through playback preparation and saving. Total elapsed
  is measured during the current session and is absent from older or reopened
  results.
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
- The planned numerical qualification covers one SPM path and remains pending.
  IPM, distributed-winding, Halbach, tutorial, and generic-field surfaces may
  be available, but they are not certified or launch-validated accuracy claims.
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
