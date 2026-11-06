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
| `rotor.ID_mm` | optional shaft bore | magnet seat (back-iron inner face), required |
| `rotor.OD_mm` | magnet seat | outside of the back-iron ring |

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

- SPM only; no tooth shoes on parametric outer stators (the slot mouth narrows to
  the gap instead); two-layer windings must be tooth coils (side by side).
- Elmer, the fixed-mesh rotation lane and the dimension overlay are not available
  for outer rotors; the solved-field view omits the air-gap ring and stator pole
  labels.

## Validation

See the validation section of the 0.5.5 release notes for the measured LRK
comparison and the self-consistency checks on the hobby designs.
