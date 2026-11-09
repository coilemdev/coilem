# Outer-rotor (outrunner) motors

coilEM solves outer-rotor surface-magnet motors through the same Design → Solve →
Results pipeline as inner rotors. There is one code path per concern: the layout
is a field of the design, and the pipeline reads explicit facts from the geometry
rather than assuming the rotor sits inside the stator.

## The design contract

`MotorConfig.rotor_layout` is `"inner"` (default) or `"outer"`. Inner designs omit
the field when saved, so every existing design, cache key and run record is
unchanged. An older app opening an outer design ignores the field and treats it as
an inner rotor; open outrunner designs in 0.5.5 or later.

For an outer rotor the fields mean:

| Field | Inner rotor | Outer rotor |
|---|---|---|
| `stator.OD_mm` | stator outside | air-gap face (tooth tips) |
| `stator.ID_mm` | bore facing the rotor | hub bore inside the yoke |
| `stator.slot_opening_mm` | mouth at the bore | mouth at the stator OD |
| `stator.tooth_shoe_*` | shoe at the bore | shoe at the stator OD |
| `rotor.ID_mm` | optional shaft bore | magnet seat (back-iron inner face), required |
| `rotor.OD_mm` | magnet seat | outside of the back-iron ring |

Tooth shoes work the same way for both layouts, at the air-gap face. With a shoe,
`slot_opening_mm` is the tooth-body opening, and the physical mouth is two
`tooth_shoe_overhang_mm` narrower. The shoulder sits `tooth_shoe_height_mm` in
from the face.

Outer rotors are SPM only. Their size floors suit RC and drone motors (stator OD
from 10 mm, magnets from 0.5 mm); inner rotors keep the original floors. The air
gap is `rotor.ID/2 − magnet thickness − stator.OD/2`, with a 0.1 mm minimum.

## Conventions

- **Pole 0's north faces the air gap**: radially inward on an outer rotor. The
  d-axis, current angle γ (from the q-axis) and six-step commutation therefore mean
  the same thing for both layouts.
- **Torque is the rotor's**, positive clockwise in the UI, for both layouts. The
  solver's field integrals (weighted stress, contour, Arkkio, MST) give the torque
  on the body inside the air gap, which for an outer rotor is the stator; the
  backend reports the rotor torque as its negative. Energy derivatives with respect
  to rotor angle are rotor torque already.
- **Phase A's flux axis is half a cycle on** for an outer rotor: a gap-facing north
  pole drives flux inward through the stator, so `phase_axis_offset_deg` adds 180°
  electrical (mirrored in the solver's `sources.rs`).

## How the pipeline handles the layout

- **Geometry.** `geometry_drawer` places outward-opening slots and inner-face
  magnets; `geometry_ir._build_outer_rotor_geometry_ir` emits the regions, tags the
  rotor OD and hub bore A=0, and records the air-gap band and steel sampling radii
  in the IR metadata.
- **Mesh.** For outer rotors the Gmsh mesher collects the A=0 nodes from the tagged
  curves, takes the air-gap band from the IR and sizes the bulk mesh to the stator
  (the inner-rotor 0.9 mm floor would leave small stators under-resolved).
- **Solver.** `MeshInfo.outer_rotor` tells Magneto2D to use the explicit A=0 nodes,
  skip the inner-rotor magnet re-tag band, weight the stator as the inner body in
  the weighted-stress torque and sample tooth/yoke flux at the given radii.
- **Unsupported paths fail loudly** (`rotor_layout.require_inner_rotor`, Elmer, the
  fixed-mesh lane, the radial magnetization fallback) instead of returning a
  silently wrong field.

## Published references

`backend/reference_models` registers pinned published designs behind one
`ReferenceModel` interface (the Prius and the LRK outrunner). The LRK 12-slot /
14-pole reference lowers the published sliding-band benchmark drawing exactly; its
stator is turned +15° with circuits B/C relabelled so its winding equals the generic
12s/14p tooth-coil map, and the ordinary current and flux-linkage code applies.
Source position θ is native rotor angle θ + 15°.

The LRK examples are held behind `VITE_COILEM_LRK_EXAMPLES=1` until the
redistribution rights of the source model's B-H curves are confirmed.

## Current limits

- SPM only; two-layer windings must be tooth coils (side by side).
- Elmer, the fixed-mesh rotation lane and the dimension overlay are not available
  for outer rotors; the solved-field view omits the air-gap ring and stator pole
  labels.

## Validation

- **LRK against its published solution.** Through the normal pipeline on the
  fine mesh, all 11 published torque points pass Phase A's mean-torque rule:
  within 8% of the published torque, or within 0.01 N·m where the published
  torque is under 0.01 N·m (owner decision, November 9, 2026). The source
  point is −0.39%, and the back-EMF fundamental is −0.62%.
  - **The stricter rule.** Until then the check used max(2%, 0.05 mN·m), and
    9 of 11 passed. The two near-zero points miss it:
    - the 40° point: 3.538 mN·m against 3.3944, 0.14 mN·m high;
    - the zero-current point: 0.008 mN·m against 0.0649, 0.06 mN·m low.
  - **Why they miss.** Both points sit where the torque changes by 1.2 to
    1.9 mN·m per electrical degree, so their errors amount to 0.02° of rotor
    position or less. At zero current, FEMM's own sliding-band model gives
    0.0075 mN·m, close to coilEM's value.
  - **How loose the new floor is.** Phase A's floor was set for larger motors.
    On this 55 mN·m motor, 0.01 N·m is loose, so these strict errors stay
    reported.
  - **Solver.** With Newton (the default since v0.5.6), every fine-mesh
    position converges. Picard stalls at one position within its
    200-iteration cap.
- **Self-consistency on hobby designs.** On the 12/14 starter and a 9/12
  18 mm design, the mean torque agrees with 1.5·p·λ·I within 0.3%, and the
  phases balance. The 9/12 design's mean torque moves less than 0.05% from the
  normal to the very fine mesh.
- **Benchmark.** Outer rotors are experimental in the app: no registered
  benchmark fixture is an outer rotor. Phase F, proposed as
  [protocol 1.8.0](../benchmarks/abcd-v1.8/README.md), adds 10 outer-rotor cases
  graded with Phase A's gates against FEMM 4.2. The
  [FEMM request](OUTRUNNER_FEMM_REQUEST.md) describes the reference run.
