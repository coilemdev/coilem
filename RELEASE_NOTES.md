# coilEM 0.4.0 Developer Preview

Prepared October 19, 2026. The source identifies as coilEM 0.4.0 and bundles
Magneto2D 0.3.3. Final-candidate qualification, installed-wheel acceptance and
publication are tracked in the [release plan](docs/RELEASE_0_4_0.md).
The measurements below retain their original source commits; they are the
baseline for the final candidate, not measurements of an untested tag.

## Motor model and solve changes

- Flux linkage credits the full slot-side turns. Fractional-slot concentrated
  windings use a coil on each tooth, with the correct two-layer slot map and
  parallel-path current. Sinusoidal current angle is measured from phase A's
  own winding axis; ideal six-step uses the corresponding public sector table.
  These corrections change affected results from 0.3.x. Recheck old comparisons
  against the current winding model rather than expecting identical values.
- Design exposes the supported winding layers and parallel paths and explains
  invalid combinations. Distributed two-layer slots follow the physical
  geometry in both meshing and visualization.
- Precise is the qualified mesh-build default. Fast is a separate experimental
  mesh-build control, independent of the Preview/Standard/High accuracy solve
  plans; its lower construction cost does not establish numerical accuracy.
- The motor-constants panel explains current and voltage conventions. Results
  present Kt and Ke in datasheet units with SI values available, alongside the
  stored operating point and model assumptions.

## Exact Pyleecan Prius examples

**Examples → Benchmarks** contains **Pyleecan Prius 8p48s · BEMF** and
**Pyleecan Prius 8p48s · Loaded torque**. They load the pinned analytic geometry,
explicit winding, magnet directions and embedded M400-50A curve:

| Case | Reference operating point |
| --- | --- |
| Tutorial BEMF | 1000 rpm, 20°C magnets, zero phase current |
| Loaded torque | 2000 rpm, 60°C magnets, 250 A peak, Pyleecan d-axis Phi0 = 140° |

The model identity, case ID, temperature and current conventions survive
save/reopen and saved-run replay. The model geometry, winding and material
are fixed; operating-point and accuracy experiments retain their actual
requests. The 2D and 3D previews use the same analytic contours, including holes.
The 3D preview is an extrusion of the 2D model, not a 3D field solve.

The [conversion notice](THIRD_PARTY_NOTICES.md#pyleecan-prius-reference-data)
records source attribution and modifications. Attribution travels with saved
reference designs. There is no affiliation with or endorsement by EOMYS,
the Pyleecan project, or Toyota. Software-model reproduction does not establish
identity with the original paper or measured hardware accuracy.

## Layout, preview and results

- Layout shows the winding as a ring with coil-side direction markers and end
  turns. Slot positions come from the actual preview polygons, including the
  reflected Prius clockwise numbering. Long parallel branches wrap within the
  panel, and the solver explanation opens without covering the wiring.
- Phases shows a one-second A/B/C current scope connected to the motor. Generic
  sinusoidal, six-step and Pyleecan d-axis conventions follow the selected
  solve. Zero-current examples show flat traces and no energized tooth tint.
- Tooth poles is an independent 2D toggle, and rotor magnets carry readable N/S
  labels. Wheel zoom uses the same motor origin as the shifted Phases drawing.
- Design health and Solve setup collapse to leave more room for the motor.
  Completed results lead with key values and a three-phase back-EMF sparkline;
  the detailed run settings remain available.
- The field view uses a fixed 0–2.0 T flux-density scale, supports combined
  stator/PM field lines and axes, and links field position to result curves.
  These displays do not extend the numerical qualification scope.
- Stored field images use lossless WebP layers, shared PM mesh data is stored
  once, and replay archives are generated on download. Deleting a run also
  removes its raw solver cache. Existing saved designs and runs remain readable.
- Release hardening improves process interruption and native Gmsh handling.
  Minimal Linux installations get an actionable missing-library diagnostic.

## Retained benchmark evidence

The [v0.4.0 evidence report](benchmarks/v0.4.0/README.md) links the full PDFs,
HTML, JSON/CSV, fixtures, reference identities and reproduction commands.

| Collection | Measured source | Retained outcome |
| --- | --- | --- |
| Windows native A/B/C/D, Precise | `5b6cb61` | 35 supported jobs; 28 PASS, 1 YELLOW, one planned unsupported legacy Prius row; every gate and value matches the preceding Windows report |
| Fresh FEMM 4.2 repeat | `0417736` | 29/29 physical payloads and extraction audits exactly match the retained reference; 1h49m05s |
| Pyleecan Prius software benchmark | `d993d76` | 17 jobs, 568 field reports, 10 original software checks pass; complete thirteen-angle curve and separate angular/Fine controls |

Tutorial line RMS is 107.513838 V versus 107.558193 V in the retained software
reference (−0.0412%). Loaded mean torque is 353.950530 Nm versus 354.953115 Nm
in the matched FEMM control (−0.2825%). The largest mean difference across the
thirteen tested angles is 0.6282% of FEMM peak. The full report preserves the
upstream discrepancies and limits of the refinement controls.

The historical [Honda Accord correlation](docs/hardware-validation/honda-accord-2005/real-winding-comparison/README.md)
uses the blind N35 assumption and simplified rotor, with no pass/fail verdict.
Its existing results are not a new 0.4.0 hardware qualification. Separate Prius
hardware correlation (#69/#82) is deferred to v0.5.0.

## Installation and compatibility

The published package installs with:

```sh
uv tool install coilem
coilem
```

Use `uv tool upgrade coilem` to upgrade after publication. Until 0.4.0 is
published, these commands continue to resolve the published release; source
and rehearsal wheels identify their own build commit and version.
See [Install](README.md#install) for platform requirements and source setup.

Wheels bundle the UI and Magneto2D, with Python 3.11–3.15 support on Windows
x64, macOS Apple silicon/Intel and Linux x86_64. The release rehearsal must
validate this candidate on all four wheel targets before publication.
The launcher normally serves at `http://127.0.0.1:2645`; browser-local state
stays with its original origin/port, and saved motor runs stay in the OS
user-data folder. New `.coilem` and existing `.openem` design files are supported.
New saves record application version 0.4.0; immutable historical results and
bundled example creation versions retain their original identities.

## Qualification and remaining limits

- Qualification covers the tested SPM and flat-buried IPM combinations in
  [Validation](docs/VALIDATION.md#qualification-status), against matched FEMM
  gates with M350-50A steel and Precise meshes. It is a fixture-based software
  comparison, not a hardware certification.
- V-shape IPM remains experimental. Its baseline peak back-EMF discrepancy is
  14.778701% (YELLOW). Fast mesh, the fixed Prius references and unmeasured
  combinations remain experimental. The legacy ORNL Prius matrix row remains
  unsupported, distinct from the two exact Pyleecan examples.
- The historical macOS record does not match the current physics-source guard.
  Current macOS numerical parity needs a new full run. Linux and Python 3.15
  full numerical parity are not established by hosted smoke/installation tests.
- The frozen reference retains REVIEW_REQUIRED limitations, including steel
  loss estimates, the Kt current base and peak-B sampling. Cogging, THD, losses,
  thermal behavior and airgap harmonics are outside the qualification gates.
- Six-step is an ideal wye current-commanded model without PWM, switching
  ripple, dead time, startup or ESC dynamics. Motor results are 2D estimates.
- Elmer is disabled, hidden, and not probed in the release environment;
  `COILEM_ENABLE_ELMER=1` enables the separately installed development adapter.
  FEMM is a data-only reference and is not bundled as a solver.
- Halbach/tutorial workflows remain experimental. There is no dedicated
  cogging results view, desktop installer, automatic update, hosted service,
  account, telemetry or motor thermal solver in this release.

The remaining release work is to freeze one clean versioned candidate, rerun
A/B/C/D and the full Prius collection, validate the installed wheels, and retain
that exact candidate identity with the reports and release assets. Tagging and
publication follow review of those results.
