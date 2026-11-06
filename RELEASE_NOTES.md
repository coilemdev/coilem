# coilEM 0.5.5 — outer-rotor motors (unreleased)

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
- **Experimental until benchmarked.** No registered benchmark fixture is an
  outer rotor, so every outer-rotor design reports experimental. Phase F,
  proposed as [protocol 1.8.0](benchmarks/abcd-v1.8/README.md), adds 10
  outer-rotor cases, from an 18 mm micro drone motor to a 100 mm hub-motor
  class. They are graded with Phase A's gates against a FEMM 4.2 collection
  still to be run ([request](docs/OUTRUNNER_FEMM_REQUEST.md)).
- **Limits.** Outer rotors are SPM only, and two-layer windings must be tooth
  coils. Elmer, the fixed-mesh
  lane, the dimension overlay and the solved view's air-gap ring are not
  available for outer rotors. A design saved with an outer rotor opens as an
  inner rotor in coilEM 0.5.1 and earlier.
- Inner-rotor results are unchanged: a benchmark subset is bit-identical to
  0.5.1. Qualification still needs the full two-platform remeasure.

# coilEM 0.5.1 — unreleased fixes

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
