# coilEM 0.5.8 Developer Preview — release candidate

This candidate bundles Magneto2D 0.6.0, up from 0.5.0 in coilEM 0.5.7 for the
solver changes below. Release qualification, platform wheel
acceptance and publication are pending; see the [release checklist](docs/RELEASE_0_5_8.md)
and [release status](PUBLICATION_STATUS.md). Historical 0.5.7 benchmark records
do not qualify the changed 0.5.8 solver sources.

- **Guided motor design.** New Design exposes parameters progressively, with
  guided setup, rotor construction previews, winding checks and clearer invalid
  input messages. Design Health stays reachable on narrow screens.
- **Clearer design and field views.** Rotor previews, 3D windings, phase controls,
  layout zoom and field legends make geometry and excitation easier to inspect.
- **Python scripting.** The [Python client](docs/PYTHON_CLIENT.md) supports
  scripted motor solves with typed inputs, results and executable examples.
- **Solve execution and timing.** Direct Newton execution, worker/thread handling,
  mesh and frame sharing, and repeated-solve reuse reduce overhead. Results and
  reports distinguish elapsed time from combined worker time. Release-specific
  speed claims await measurements of this candidate.
- **More useful results and reports.** Partial analyses explain unavailable
  losses and efficiency; incomplete totals are labelled Known loss subtotal.
  PDF currents use A peak, resistance rows avoid duplicates, and diagnostic
  plots handle empty bore contours.
- **Saved runs and tutorials.** Pruned runs keep static results and explain why
  playback is unavailable. Tutorial scale bars follow the displayed geometry;
  capstone completion requires a current solved design meeting its targets and
  a completed run.

## Known limitations

V-shape bridge thickness is a minimum clearance; other geometry inputs also
control the actual bridge. Magnet coverage does not control V-shape pockets.
The [mesh sensitivity study](docs/VSHAPE_MESH_SENSITIVITY_285.md) found material
changes between Fine and Very Fine; spatial convergence remains unproven
([#285](https://github.com/coilemdev/coilem/issues/285)). A warning does not
establish numerical accuracy. Its release disposition remains pending.

Windows cancellation reliability still requires repeated platform acceptance
([#234](https://github.com/coilemdev/coilem/issues/234)). Sector models and
opt-in pole-pitch mesh reuse are excluded from this candidate. Hardware accuracy,
3D end effects and Experimental outputs remain outside any software parity
claim; see [Validation](docs/VALIDATION.md).

# coilEM 0.5.7 Developer Preview

Prepared November 11, 2026. coilEM 0.5.7 bundles Magneto2D 0.5.0 and the
combined [protocol 1.10.0 A–F benchmark](benchmarks/af-v1.10/README.md).
The current [Windows](benchmarks/records/windows-x86_64.json) and
[macOS](benchmarks/records/macos-arm64.json) records retain measured candidate
`4b41f837f3d89d4fbc836be54ecafff4729491c0`: 68 supported cases and all 468
registered gates pass on each platform, with the planned unsupported Prius
suite row retained. The separate complete Prius collections pass all ten
software checks on both platforms. The application version changes without
changing measured physics; field commits and historical evidence are not relabeled.

- **A–F in the normal benchmark.** `coilem benchmark` includes cogging and
  outer-rotor cases alongside SPM, IPM, distributed winding and six-step
  excitation. The 69-case selection runs 75 jobs against 68 frozen reference
  records; routine native comparisons need no FEMM installation. The
  repository-owned reference adapter adds batching, per-position resume and
  more reliable progress reporting for reference collection.
- **Qualification stays within the measured scope.** Sinusoidal concentrated
  outer-rotor designs with one or two winding layers can be Qualified;
  distributed and ideal six-step outer-rotor designs remain Experimental.
  Cogging qualification covers qualified inner-rotor designs and requires the
  registered very-fine mesh for distributed windings. Outer-rotor d/q flux
  linkage and magnet-temperature outputs remain Experimental. Changed or
  unverifiable physics still invalidate historical qualification labels.
- **More reliable meshing and cancellation.** Gmsh's runtime owner survives
  short-lived meshing threads, startup failures propagate and can be retried,
  and Windows solver workers use per-pool cancellation markers. Benchmark and
  release checks bind the measured Gmsh and meshio versions, including both
  separate Prius reports. Custom B–H steels honor the linear permeability override.
- **Halbach workflows and exports.** Cylindrical and linear arrays use the
  motor workspace's Design, Solve and Results layout. Narrow screens retain
  the parameter list and zoom controls, invalid values leave the workspace
  usable, and linear-array results gain exports.
- **Cogging playback and result comparisons.** A cogging-only run stores its
  existing no-current positions as field frames, so the Field view can play
  the sweep. Compare preserves the precision of small torque values and the
  correct cogging metrics.
- **Design views and tutorials.** Refreshed landing, 3D and canvas controls,
  combinable field layers and a consistent layout across the ten lessons
  improve the workflow. QA fixes preserve tutorial completion and sequence
  state across reloads and improve Design and Solve behavior.

These are software parity and workflow checks. Hardware accuracy, 3D end
effects and the other Experimental performance outputs remain outside the
qualified scope; see [Validation](docs/VALIDATION.md).

## Reproduce this record

Install coilEM 0.5.7 after publication, then run:

```sh
coilem benchmark --list
coilem benchmark --quick --out benchmark-output/057-quick
coilem benchmark --phase E --phase F --out benchmark-output/057-ef
coilem benchmark --out benchmark-output/057-af
coilem benchmark --resume --out benchmark-output/057-af
```

The complete-grid requests, frozen reference components and numerical gates
are unchanged. Windows and macOS installations compare their installed
physics with the records measured at `4b41f837f3d89d4fbc836be54ecafff4729491c0`.
The [Windows report](benchmarks/qualification-4b41f837f3d8/windows-x86_64/report/benchmark_report.md)
and [macOS report](benchmarks/qualification-4b41f837f3d8/macos-arm64/report/benchmark_report.md)
retain the full measurements; the separate Prius evidence is linked by each
platform record. A Linux replay is not a Linux numerical qualification.

# coilEM 0.5.6 Developer Preview — release candidate

Prepared November 9, 2026. This candidate identifies as coilEM 0.5.6 with
Magneto2D 0.5.0. The frozen post-version-bump candidate passes
[Windows/macOS A-D and Prius qualification](benchmarks/qualification-e9eb89e818ed/README.md).
Main integration, release tagging and package publication are pending; see
[release status](PUBLICATION_STATUS.md) and [the release PR](https://github.com/coilemdev/coilem/pull/232).

- **Newton by default.** The app and the registered A-D requests use Newton.
  Proposed E/F requests explicitly use Newton as well. Frozen FEMM inputs,
  comparison gates and existing review requirements are retained.
- **Less solve overhead.** Mesh work and field processing stay in the workers;
  field processing overlaps native angle solves, native I/O is leaner, and
  solution-reuse fallback solves remain parallel.
- **Two-layer solution reuse.** Eligible conformal two-layer slot-pitch
  rotations reuse physical-layer contributions. Ambiguous or incompatible
  cases continue through real native solves under the existing excitation gate.
- **Playback readiness.** Automatic field playback waits for saved-run images
  to be drawn; image generation stays deferred during solving.
- **Simpler design toolbar.** The regions and build-time readouts are removed.

The [Windows FEMM/Native report](docs/benchmarks/windows-femm-release-v056-20261109.md)
retains the earlier `8b6b394`/`11aa06b` baseline results, including exact
reproduction of all 58 fresh FEMM case/control results. It predates the
two-layer integration and this application version bump. The final candidate's
own measurements and qualification record retain field commit `e9eb89e`;
historical field commits are not relabeled.

Outer rotors and cogging remain experimental. Their proposed suites do not
extend the registered A-D/Prius release scope; inherited review findings remain
visible. No hardware or broader performance qualification is claimed.

# coilEM 0.5.5 Developer Preview — outer-rotor motors

Prepared November 8, 2026. The [release qualification gate](benchmarks/v0.5.5/release-qualification.json)
passes for registered A-D parity and the Prius software checks, measured at
`34de0f4` on Windows and macOS. Outer-rotor motors are new and experimental.
The application version is 0.5.5. The bundled Magneto2D solver keeps version
0.4.0 although it gains outer-rotor support; inner-rotor results are unchanged,
and its version advances with the next requalification.

- **Outrunners in the normal workflow.** Design has an **Inrunner / Outrunner**
  switch. Outer-rotor surface-magnet motors are edited, meshed, solved and
  reported like inner rotors: outward-opening slots, magnets on the rotor's inner
  face, a hub bore, and drone-size limits. A starter 14-pole / 12-slot outrunner
  ships as an example. Conventions, field meanings and limits are in
  [docs/OUTRUNNER.md](docs/OUTRUNNER.md).
- **Same conventions for both layouts.** Torque is the rotor's, positive
  clockwise; pole 0's north faces the air gap, so current angle and six-step
  commutation mean the same for an outrunner.
- **LRK 12-slot / 14-pole reference.** The published sliding-band benchmark
  outrunner runs through the normal pipeline as a pinned reference, next to the
  Prius. Its examples stay hidden until the source data's redistribution rights
  are confirmed.
- **Tooth shoes on outer stators.** An outrunner's teeth can carry shoes at the
  stator OD, set the same way as an inner rotor's: shoe height, and overhang per
  side of the tooth body. Most real outrunners have them. The Benchmarks menu
  adds one: a published 36-slot / 40-pole robot-joint outrunner, with its
  measured back-EMF and torque in its description.
- **A second published outrunner.** The Benchmarks menu adds Model B of the
  36-slot / 40-pole drone outrunners in Koo & Shin, *Energies* 19(16):3845 (2026).
  Its measured back-EMF and torque are in the design's description: coilEM's
  back-EMF lands as close as the authors' own 2D FEM, and its torque about 4% low.
- **Back EMF as rms and peak.** The Results card adds a small table of the phase
  and line-to-line back-EMF as rms and peak, since papers and datasheets often
  quote a peak; the peak comes from the solved waveform, harmonics included, and
  peak-to-peak is twice it. The Back EMF chart gains an RMS / Peak switch that
  shows each trace's value in its legend.
- **Examples by rotor layout.** The Examples menu lists inrunners and outrunners
  side by side in each group.
- **Outrunners in 3D.** An outer-rotor design's 3D view is built like an inner
  rotor's instead of extruding its cross-section: the stator's teeth point out
  from its hub with a wound coil on each, and the rotor is a can round them with
  its magnets on the inner face. A spoked end bell closes the can and is clamped
  to the shaft, so the shaft turns with the rotor; the shaft runs in two bearings
  held by a fixed tube in the stator hub, and the stator mount behind (under End
  caps) bolts the stator to the frame. The explode, part toggles and phase links
  work as before. Published reference motors still extrude their cross-section.
- **Phase wiring as it is wound.** In both layouts the 3D view now draws each
  phase as one continuous wire: every coil has its own start and finish lead, and
  each finish crosses behind the stack to the next coil's start, a short hop
  between neighbouring teeth, from the drive lead to the star point.
- **Sector view for thin-ring motors.** An outrunner whose active ring is a thin
  band (radial thickness up to half its outer radius) opens zoomed on the top of
  the ring in Design and in the solved field, not on the empty hub. **‹ ›**, or
  the arrow keys over the view, turn the motor under the view with a short
  animation, so every sector reads the same way up with its labels level. A dial
  shows where on the ring you are and turns there when clicked; **Sector** and
  **Fit** switch between the ring and the whole motor.
- **Slower preview and field playback.** The Design preview's speed and the
  solved-field playback in Solve and Results go down to 0.1 RPM, in tenths below
  1 RPM, so the phases, the tooth poles and the field can be followed slowly. The
  phase scope's frequency and rev/s keep two figures at these speeds.
- **Up to 64 poles.** The pole limit rises from 32 to 64 for both layouts, so
  36-slot / 40-pole robot-joint and drone outrunners and 46–48-pole hub motors
  can be modelled. Slots were already allowed up to 96.
- **Smaller saved runs.** A saved run keeps each field frame as float32 arrays
  in an xz stream (`.f32.xz`), a quarter to a third of the gzipped JSON, linked
  from the solve cache instead of copied. Its playback images stay out of the
  run: they wait in the solve cache and are drawn again from the run's frames
  when the cache has dropped them. A run of the 8-pole / 12-slot example drops
  from about 242 MB to about 61 MB, its frames and result
  ([public issue 212](https://github.com/coilemdev/coilem/issues/212)).
  The solve still reads its physics from the cache's full-precision JSON, so
  results are unchanged, and runs saved earlier still open.
- **Open an earlier run's results.** **Previous runs** has **Open results** for
  each completed run: its stored result opens in Solve and Results, field
  playback included, as stored evidence for those inputs.
- **Older runs give up field playback.** Each design keeps field playback for its
  newest 5 runs (`COILEM_FIELD_PLAYBACK_KEEP_RUNS`); older runs keep their
  results, report and design, and **Manage previous runs** marks them. A full
  workspace removes the oldest runs' playback before it refuses a solve.
- **Experimental, with first FEMM agreement.** Every outer-rotor design still
  reports experimental. Phase F, proposed as
  [protocol 1.8.0](benchmarks/abcd-v1.8/README.md), adds 10 outer-rotor
  cases, from an 18 mm micro drone motor to a 100 mm hub-motor class, graded
  with Phase A's gates. Against a FEMM 4.2 collection run on Windows
  ([request](docs/OUTRUNNER_FEMM_REQUEST.md)), all 10 cases pass (60/60
  gates): the worst mean-torque error is 0.86% and the worst Back-EMF
  fundamental and peak errors are 0.31% and 0.36%. Qualifying outer rotors
  needs the same comparison on macOS as well.
- **Small readings plot to scale.** Result charts no longer squeeze a
  waveform smaller than one unit into the top of the plot. Small readings show
  in mN·m or mV, axis labels use round steps, and nothing reads −0.00.
- **Diagnostics.** Solver convergence moves to a Diagnostics section at the end
  of Results. It leads with a plain verdict and four facts, charts the share
  of the iteration limit each rotor position used, and lists only the angles
  that need a look, with both sweeps side by side. Solver settings stay under
  Technical details; every position's record stays in the CSV.
- **Limits.** Outer rotors are SPM only, and two-layer windings must be tooth
  coils. Elmer, the fixed-mesh
  lane, the dimension overlay and the solved view's air-gap ring are not
  available for outer rotors. A design saved with an outer rotor opens as an
  inner rotor in coilEM 0.5.1 and earlier.
- **Inner-rotor results are unchanged.** The full two-platform remeasurement
  (A–D and the Prius collection) matches 0.5.1: macOS values are identical
  and Windows values agree within 3×10⁻⁸ relative, with every supported case
  passing 336/336 gates on each platform. The reviewed protocol 1.6 FEMM
  references are reused after owner review, supported by a fresh FEMM
  collection of all 46 cases
  ([decisions](benchmarks/qualification-34de0f4ca160/owner-decisions.json)).

# coilEM 0.5.1 Developer Preview

Prepared November 6, 2026. The [release qualification gate](benchmarks/v0.5.1/release-qualification.json)
passes for registered A-D parity and the Prius software checks. The
[release plan](docs/RELEASE_0_5_1.md) records the freeze, owner decisions and
packaging/publication steps. The application version is 0.5.1;
the bundled Magneto2D solver remains 0.4.0.

- Solve gains guided Analysis choices and standalone no-current analyses;
  torque–speed maps are opt-in, and partial map results survive cancellation.
- The app header shows the running software version. Results and exports
  report recorded solver convergence. Performance PDFs use three decimal places.
- Cogging diagnostics bind source identity and validate waveform summaries.
  The owner chose to keep cogging experimental for this release. Proposed
  Phase E remains unregistered and its fresh references under review; the
  unchanged native requests retain two disclosed YELLOW cases.
- Windows A–D evidence at `a4f9f4d` records 46 PASS and 336/336 gates, with
  one planned unsupported legacy ORNL Prius. An independent overnight run
  completed all 46 fresh FEMM references; every waveform exactly matches the
  reviewed reference. The [evidence packet](benchmarks/windows-v051-20261105-a4f9f4d/README.md)
  preserves outcomes, waveforms, source identities, retry history and hashes.
- Both Windows and macOS record 46 A-D PASS and 336/336 gates; each complete
  Prius collection has 17 jobs, 568 fields and all ten software checks passing.
  The owner accepted the near-zero macOS 180-degree Prius observation change
  from 0.026539 to 0.030181 Nm, preserving the original values and limits.
  No additional hardware or performance qualification is claimed.
- Qualification automation binds collections to immutable candidate refs and
  retains failed attempts while allowing verified collection recovery.

- Correct the performance CSV header to `section,field,unit,value,sample_index`.
  coilEM 0.5.0 accidentally labelled its third and fourth columns `value,unit`,
  although the data already contained unit then value. Data order, precision
  and the `coilem.performance_report.v1` identifier are unchanged. Consumers
  that worked around the 0.5.0 header should remove that swap for new exports;
  retain the workaround when reading an original 0.5.0 file.

# coilEM 0.5.0 Developer Preview

Prepared November 3, 2026. coilEM 0.5.0 is the performance release
([public issue 143](https://github.com/coilemdev/coilem/issues/143)): it answers
"does this motor meet my spec across its operating range?" with torque–speed,
losses and efficiency. It bundles Magneto2D 0.4.0.

The release is measured at clean candidate
`88aae101fd487795e7fe5300737679f4133790fd` on Windows and macOS under
[benchmark protocol 1.6.0](benchmarks/abcd-v1.6/README.md), and the
[release qualification gate](benchmarks/v0.5.0/release-qualification.json)
passes. Every new number either passes a reference gate or is labelled
experimental with its reason. The [release plan](docs/RELEASE_0_5_0.md) has the
full detail and the [evidence index](benchmarks/v0.5.0/README.md) every report.

## Torque–speed, efficiency and d/q

- Results has a **Torque–speed** tab. It solves a flux-linkage map over current
  magnitude and angle (0° to 90°): 5 × 7 points on Preview, 7 × 10 on Standard.
  The map shows its progress, can be cancelled, resumes from its finished
  points and is reused for a lower peak current.
- From the map it draws peak and continuous **torque–speed and power–speed
  curves** for the entered DC bus, currents and top speed, each sample labelled
  MTPA, field weakening or MTPV, with the solved point marked.
- An **efficiency map** over the torque–speed plane, under MTPA or least-loss
  control, and apparent Ld and Lq against current with the MTPA trajectory.
- A **d/q card** in Results gives Ld, Lq, the saliency and the characteristic
  current, then **Torque–λdq agreement**: the solved torque against
  1.5·P·(λd·iq − λq·id), which includes reluctance torque.

## Winding, losses and magnet temperature

- Design takes a wire, strands in hand, an end-turn extension and a winding
  temperature, and shows the phase resistance, mean turn length and slot fill.
  Without a wire, one is derived to fill 45% of the slot, and the app says so.
- A **Losses** card gives copper loss, stator iron loss (hysteresis and eddy
  current, teeth and yoke) and efficiency at the solved point, with a map of
  where the loss is. Iron loss is available for M350-50A, and for M400-50A in
  the pinned Pyleecan Prius. Solve takes a constant **mechanical loss**.
- Solve takes a **magnet temperature**: Br and HcJ are derated linearly from
  20 °C with the grade's cited coefficients for N35, N42, N48, N52 and N48SH.
  Above a grade's rating the run carries a warning.
- The Pyleecan Prius gains an iron loss and a copper loss from its published
  conductor: 612 W iron, 6.72 kW copper and 90.9% efficiency at its loaded
  point, with torque unchanged at 353.95 N·m.

## Exports and smaller changes

- The Torque–speed tab downloads a performance PDF and CSV, an id/iq table and
  the map points. The run PDF and CSV add the d/q record, losses, efficiency,
  winding and magnet temperature.
- Every new output carries its status and reason in the UI, the PDFs and the
  CSVs.
- Kt is labelled per peak or per rms ampere everywhere
  ([#153](https://github.com/coilemdev/coilem/issues/153)), and the Pyleecan
  Prius's tooth and yoke widths display rounded
  ([#154](https://github.com/coilemdev/coilem/issues/154)).
- The nonlinear stopping test now measures the actual permeability mismatch
  ([#11](https://github.com/coilemdev/coilem/issues/11)), and each result
  records its convergence per position
  ([Nonlinear convergence](docs/NONLINEAR_CONVERGENCE.md)). Showing it in
  Results (#12) is planned for 0.5.1.

## What is qualified

| Output | Status |
| --- | --- |
| Torque and back EMF of the tested combinations | Qualified, as in 0.4.0, against the [reviewed protocol 1.6.0 references](benchmarks/reference-baselines/protocol16-reviewed-20261103/README.md) |
| Phase resistance and copper loss, with a wire | Qualified by the hand-calculation gate |
| Loaded λd and λq | Qualified for a qualified single-layer concentrated SPM or flat-buried IPM design under sinusoidal current at γ 0°–60° |
| Magnet temperature derating | Qualified for a qualified design from 20 °C to 100 °C |
| Ld, Lq, saliency, characteristic current | Experimental: the d/q gates do not bound them tightly |
| Flux-linkage map, torque–speed, efficiency map, iron loss, efficiency | Experimental |

The d/q and temperature gates measured up to twice their fixtures' current, at
the derated Br; the grade coefficients are catalogue values. The owner set
these scopes on November 3, 2026 ([decisions](benchmarks/v0.5.0/owner-decisions.json)).
[Validation](docs/VALIDATION.md#050-performance-outputs) gives each output's
claim boundary.

## Benchmark evidence

- **A/B/C/D, protocol 1.6.0:** 52 supported jobs on each platform. Windows and
  macOS each record 46 PASS, the planned unsupported legacy ORNL Prius and
  336/336 gates ([Windows](benchmarks/candidate-qualification-20261103/windows/report/benchmark_report.md),
  [macOS](benchmarks/candidate-qualification-20261103/macos/report/benchmark_report.md)).
  The two platform records match each other within 0.36 of their tolerances.
- **References:** 46 FEMM 4.2 records; the 29 legacy cases reproduce the
  0.4.0 references exactly. The owner accepted the reviewed bundle on
  November 3, 2026.
- **Pyleecan Prius:** the exact-candidate Windows collection passes all 10
  software checks across 17 jobs and 568 field reports
  ([report](benchmarks/candidate-qualification-20261103/prius/README.md)).

Two fixes change numbers that 0.4.0 qualified: the slot current now comes from
each coil side's meshed area, and the nonlinear stopping test is corrected.
On the 24 loaded cases both releases measured:

| Group | Cases | Mean torque error vs FEMM | Worst torque error | Mean back-EMF error |
| --- | ---: | --- | --- | --- |
| A, SPM | 8 | 0.27% → 0.33% | 0.48% → 0.63% | 0.07% → 0.08% |
| B, flat IPM | 6 | 0.34% → 0.31% | 0.64% → 0.66% | 0.33% → 0.30% |
| B, V-shape IPM | 6 | 4.55% → 5.13% | 5.90% → 7.05% | 2.39% → 6.50% |
| C, distributed | 4 | 2.67% → 2.87% | 4.90% → 5.20% | 0.18% → 0.23% |

These are the macOS figures; Windows differs by at most 0.04 points.

## Installation and compatibility

The published package installs with:

```sh
uv tool install coilem
coilem
```

Use `uv tool upgrade coilem` to upgrade. Until 0.5.0 is published, these
commands resolve the published 0.4.0; source and rehearsal wheels identify
their own build commit and version. See [Install](README.md#install) for
platform requirements and source setup.

Wheels bundle the UI and Magneto2D, with Python 3.11–3.15 support on Windows
x64, macOS Apple silicon/Intel and Linux x86_64. The launcher normally serves
at `http://127.0.0.1:2645`; saved motor runs stay in the OS user-data folder.
New `.coilem` and existing `.openem` design files are supported, and new saves
record application version 0.5.0.

`coilem benchmark` now runs protocol 1.6.0: about 6 minutes with `--quick`,
about 2 hours in full.

## Qualification and remaining limits

- Qualification is agreement with FEMM on the measured fixtures, with M350-50A
  steel and Precise meshes; it is a software comparison, not a hardware
  certification. Motor results are 2D estimates.
- **V-shape IPM** stays experimental although all six fixtures pass: its mean
  fundamental back-EMF error grew from 2.4% in 0.4.0 to 6.5%, and the
  refined-reference control does not establish spatial convergence.
- **Losses not modelled:** magnet and rotor eddy-current loss, AC copper loss
  and inverter loss. Iron loss comes from guaranteed grade limits and covers
  the stator only. Mechanical loss is one constant at every speed.
- **Torque–speed** assumes sinusoidal steady-state current without inverter
  drops, dead time, PWM ripple or overmodulation. The continuous curve is a
  current limit, not a thermal rating; winding and magnet temperatures are
  inputs, and irreversible demagnetisation is not modelled.
- **Hardware correlation** with the ORNL Prius and Honda Accord is planned after
  0.5.0. The legacy ORNL Prius benchmark row remains unsupported, distinct from
  the exact Pyleecan Prius.
- Six-step is an ideal current-commanded model. Fast mesh, the fixed Prius
  references and unmeasured combinations remain experimental. Linux and
  Python 3.15 full numerical parity are not established by the hosted tests.
- Elmer is disabled and not probed in the release environment; FEMM is a
  data-only reference and is not bundled. There is no thermal solver, desktop
  installer, automatic update, hosted service, account or telemetry.
