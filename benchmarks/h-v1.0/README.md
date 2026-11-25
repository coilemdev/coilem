# Benchmark Phase H: thermal

Phases A to G compare coilEM's electromagnetic results with FEMM. Phase H does
the same for the thermal estimate. It is a fixed set of 42 thermal problems
that any tool can solve, coilEM's answer to each, and a format for another
tool's answer so the two can be graded.

Protocol H-1.0.0, registered 2026-11-23. The stored results and the FEMM 5.0
references are kept in the private repository; see [Stored records](#stored-records).

## What a case is

A case is one design at one cooling level in one scope. Everything a thermal
tool needs is fixed in [benchmark_spec.json](benchmark_spec.json):

- **The design.** Seven designs, stored in [fixtures/](fixtures/) as plain
  design files that `coilem check` and `coilem solve` open as they are.
- **The heat in each part, in watts.** Split 10 : 3 : 7 : 1 : 1 between
  winding, stator teeth, stator yoke, magnets and rotor iron. The total for
  each design and cooling level puts coilEM's slot winding about 80 K above
  the surroundings. Heat is fixed, so copper-temperature feedback is off and
  every problem is linear.
- **The conductivities**, in W/(m K): slot 1, steel 20, copper 385, magnets 8,
  housing 205, slot liner 0.2.
- **The cooling**, as coefficients and resistances (below).
- **The surroundings**, at 25 C.

These are prescribed values that every tool shares. They are not measurements
and Phase H does not test whether they are right for a real motor.

### Designs

| Id | Design | Rotor |
|---|---|---|
| `spm_8p12s_concentrated` | Surface magnets, 8 poles and 12 slots, tooth coils | inner |
| `spm_12p36s_distributed` | Surface magnets, 12 poles and 36 slots, distributed winding | inner |
| `ipm_14p18s_flat_buried` | Flat buried magnets, 14 poles and 18 slots | inner |
| `ipm_10p12s_v_shape` | V-shape buried magnets, 10 poles and 12 slots | inner |
| `outrunner_14p12s` | 14 poles and 12 slots, 28 mm stator | outer |
| `joint_outrunner_36s40p` | 40 poles and 36 slots, robot-joint size | outer |
| `drone_outrunner_36s40p` | 40 poles and 36 slots, drone size | outer |

### Cooling levels

An inner-rotor stator sits in a housing. An outer-rotor stator sits on a hub
and mount, and its rotor shell is the outside of the motor.

| Rotor | Level | Outside surface, W/(m2 K) | Air gap, per surface | End space | Mount, K/W |
|---|---|---|---|---|---|
| inner | Still air | 10 | 20 | 10 | n/a |
| inner | Forced air | 60 | 40 | 25 | n/a |
| inner | Liquid jacket | 1000 | 40 | 25 | n/a |
| outer | Still air | 10 | 20 | 10 | 10 |
| outer | Prop wash | 80 | 40 | 25 | 10 |
| outer | Cooled mount | 10 | 20 | 10 | 1 |

Also fixed: housing wall 3 mm, stator contact 0.001 m2 K/W, and in the full
scope a 0.2 mm slot liner, 2 K/W from bearings to housing and 3 K/W from rotor
to bearings.

The strongly cooled levels are there on purpose. With still air, nearly all of
the temperature drop is across the outside surface, and any tool that gets the
surface right agrees. With a liquid jacket or a cooled mount, conduction inside
the motor carries most of the drop, and that is where tools differ.

### Two scopes

- **in-plane:** only what a flat cross-section contains. All copper heat is in
  the slots. End windings, the air around them, the bearings and the slot
  liner are left out. A planar finite-element tool such as FEMM solves exactly
  this problem.
- **full:** the whole estimate, with end windings, end-space air, bearings and
  the slot liner. The share of copper heat outside the stack follows the
  winding's own geometry and is recorded with the result. This needs a
  three-dimensional or lumped tool, or a bench test, to compare with.

## How a result is graded

For each part a reference reports, coilEM's temperature is compared with the
reference temperature. A part passes when the difference is within 10% of the
reference's rise above the surroundings, or 2 K if that is larger. Up to twice
that is YELLOW, beyond it FAIL. A case takes its worst part. A case with no
reference is NOT_COMPARED. The bands are registered in the specification and
were set before the first comparison was graded.

## Run it

    python -m tools.run_phase_h            # solve, grade, write results/coilem.json and RESULTS.md
    python -m tools.run_phase_h --check    # fail if those files are not what this build gives

It needs no solver and takes a few seconds. Where the stored record is present,
`tests/test_thermal_phase_h.py` runs the same check, so a change to the thermal
model that moves a Phase H number shows up as a failing test until the results
are regenerated and reviewed.

## Add a reference from another tool

A reference is one JSON file per case in `references/<tool>/`:

    {
     "case_id": "outrunner_14p12s__still_air__in_plane",
     "spec_sha256": "<sha256 of benchmark_spec.json>",
     "tool": "Name and version of the tool",
     "temperature_C": {"winding": 100.0, "teeth": 95.0, "yoke": 90.0, "magnets": 60.0, "rotor": 55.0},
     "exit_W": {"mount": 5.0, "shell": 1.0}
    }

The numbers above are placeholders, not a reference.

`temperature_C` holds the area-weighted (or volume-weighted) mean temperature
of each part; give the parts the tool can report and leave out the rest.
`exit_W` is optional. A file whose `spec_sha256` is not the current
specification's is refused.

For an in-plane case, this writes the whole problem for another tool: exact
region outlines as lines and arcs, each region's material, conductivity and
heat density, and the coefficient on each cooled face.

    python -m tools.run_phase_h --export-request outrunner_14p12s__still_air__in_plane --out request.json

Three things in that export make a flat model match what the estimate assumes:

- Each cooled face carries one coefficient that stands for everything between
  that face and the surroundings: contact, housing wall or mount, and the
  outside film, including the end faces the estimate counts.
- The air gap is a solid whose conductivity reproduces the two gap films across
  its real thickness.
- The air pockets beside the magnets conduct like the magnets, because the
  estimate puts the rotor-side film on the whole rotor circumference.

The FEMM references were made this way by `python -m tools.phase_h_femm`
(FEMM 5.0, two meshes per case). Each reference records both meshes'
temperatures and FEMM's own heat balance, so its mesh error can be checked.

## Stored records

coilEM's stored answers (`results/coilem.json`), their page (`RESULTS.md`) and
the FEMM 5.0 references (`references/femm5/`) are generated measurements. They
are kept in the private repository, where release qualification runs (see
[releasing](../../docs/RELEASING.md)), and are not part of the public source or
the wheel. In a checkout without them, `python -m tools.run_phase_h --check`
says there is nothing to check and the tests that compare against them skip.

To regenerate them, run `python -m tools.phase_h_femm` on a machine with FEMM
5.0 to write `references/femm5/`, then `python -m tools.run_phase_h` to solve
and grade every case. Without references the record holds coilEM's answers and no comparison.

## What Phase H does not test

- Whether the cooling coefficients, contact resistance and conductivities are
  right for a real motor. Every tool is given the same values.
- coilEM's losses. The heat is prescribed.
- Warm-up over time, or copper resistance rising with temperature.
- Anything measured. The published-measurement check is
  `python -m tools.check_thermal_published` (see [thermal-v0.6](../thermal-v0.6/README.md)).
