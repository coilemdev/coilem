# Benchmark Phase G: losses

Phases A to F compare torque, back EMF and cogging with FEMM. Phase G does the
same for the loss numbers of a full-motor solve. The stored results and the
FEMM records they are graded against are kept in the private repository; see
[Stored records](#stored-records).

## What is solved

Four motors, each at no load and at one load, each at 1500 and 3000 rpm: 16
operating points.

| Motor | Load current, peak |
|---|---|
| Inner-rotor SPM, 8 poles, 12 slots, concentrated winding | 20 A |
| Inner-rotor flat IPM, 8 poles, 12 slots (FSAE) | 50 A |
| Inner-rotor SPM, 8 poles, 24 slots, distributed winding | 8 A |
| Outer-rotor SPM, 10 poles, 12 slots, single-layer winding | 15 A |

All use a sinusoidal drive with the current on the q axis, M350-50A steel, N42
magnets, 0.8 mm wire with two strands, a 20 °C winding and no mechanical loss.
These are benchmark assumptions, not measured motors.

## What is graded

**Stator iron loss, copper loss and phase resistance, against FEMM.** Each
point is solved through the public Python client, as a user script would solve
it. Hysteresis, lamination eddy and total stator iron loss must be within 10%
of FEMM or 1 mW. DC copper loss and phase resistance must be within 1%. The
FEMM records are in `references/femm-stator-copper-20261117` and were
collected with FEMM 4.2 on 2026-11-17.

**Rotor iron loss, on its own checks.** Each motor and load is solved once over
a full mechanical turn of 384 rotor positions, plus one more solve at the end
of the turn. The loss is then worked out from 96, 192 and 384 of those
positions, at both speeds. Two things are required:

- the field at the end of the turn equals the field at its start, to 1e-6 T at
  most and 1e-7 T on average;
- doubling the number of positions changes hysteresis, lamination eddy and
  their sum by under 5% or 1 mW, for both doublings.

All three of the 96-, 192- and 384-position results are required: a missing
one fails the doublings it belongs to.

**Rotor iron loss, against FEMM.** FEMM 5 solved the same eight histories over
the same 384 positions on one fixed FEMM mesh each (`tools/phase_g_femm`); the
records are in `references/femm-rotor`. Their loss is worked out by
`tools/rotor_loss_reference.py`, which shares no code with coilEM's. coilEM's
384-position hysteresis, lamination eddy and total must each be within 10% of
FEMM or 1 mW; without a 384-position result the comparison fails.

The rotor iron loss turn meshes the air gap, slot mouths and magnet corners at
half the usual smallest size and solves every position to a Newton tolerance
of 1e-7, whatever the solve quality. Without that, the rotor iron loss reads
high: the usual mesh overstates the ripple the slot mouths put on the rotor,
and a Newton solve stopped early leaves a saturated IPM's pocket corners
jittering from one position to the next.

## Running it

```bash
python -m tools.run_phase_g --work ~/coilem-phase-g-work
```

Windows PowerShell, from a source checkout set up as in the top-level README:

```powershell
.\.venv\Scripts\python.exe -m tools.run_phase_g --work D:\coilem-phase-g-work
```

This needs the Magneto2D solver and takes one to two hours on a laptop on
mains power (each rotor history is 385 solves). FEMM is not needed. Finished
points are kept in the work folder, so a stopped run continues where it was:
restart it with the same command.
`--only outer_spm` solves one motor and prints its grades without writing
anything here.

The work folder's `candidate.json` records the build that solved its points:
the source commit, whether the backend, client, material or solver sources
differ from that commit, a hash of the Python sources and data as they are,
a hash of the Magneto2D executable the solves ran, the specification and
fixture hashes, and the Gmsh and meshio versions. A run from any other build
refuses the folder and says what differs, so points from before a fix are
never recorded as the fix's. Use a new work folder for a new build, or add
`--discard-work` to delete the points kept in the folder (nothing else in it)
and solve them again. A work folder from before this record was kept is
refused the same way. Each point is written to a temporary file and then
renamed, so a stop while writing leaves that point to be solved again.

One run at a time can use a work folder. A run holds an operating-system lock
on `.phase-g-run.lock` in the folder from before it checks `candidate.json`
until its result is assembled, and removes the file when it ends; if the run is
killed, the system releases the lock. A second run on the same folder, with or
without `--discard-work`, is refused at once and changes nothing in it.

A full run, and `--regrade` (which grades the stored record again, for example
after new FEMM records), store the record and its page only when the record
holds every registered case, rotor history, speed, position count and value.
Both are rendered before either is written, and neither replaces the stored
file until both are written, so a refused or failed write leaves the stored
record and page as they were.

```bash
python -m tools.run_phase_g --check
```

solves nothing. It grades the stored record again and rebuilds the page from
it, and fails if either differs from what is stored. The test suite runs this
where the stored record is present.

## Stored records

The record of a run (`results/coilem.json`), its page (`RESULTS.md`) and the
FEMM records (`references/femm-stator-copper-20261117` and
`references/femm-rotor`) are generated measurements. They are kept in the
private repository, where release qualification runs (see
[releasing](../../docs/RELEASING.md)), and are not part of the public source or
the wheel. In a checkout without the record, `python -m tools.run_phase_g
--check` says there is nothing to check and the tests that compare against
these files skip.

Grading needs the FEMM records. `benchmark_spec.json` pins the SHA-256 of each
FEMM 4.2 stator record, so a supplied record is checked before it is used. The
FEMM 5 rotor records are regenerated from the committed requests in
`femm-requests/` with `tools/phase_g_femm` (see its README). With the records
in place, `python -m tools.run_phase_g --work DIR` writes a new record and page.

## Limits

- Both tools use the same M350-50A loss coefficients. Agreement shows that the
  fields and the arithmetic agree, not that the coefficients describe a real
  motor. Every loss here stays Experimental.
- For the outer-rotor motor the rotor ring is treated as laminated steel. A
  solid steel shell carries larger eddy currents, which are not calculated.
- Not included: magnet and other solid-part eddy currents, AC winding loss,
  inverter loss, and excess-loss, minor-loop and rotating-flux corrections.

## Relation to the registered A-F suite and to the earlier Phase G

Phase G is separate from the registered A-F suite. It does not change that
suite, its references, its gates or its protocol version, and
`coilem benchmark` does not run it.

An earlier Phase G (`benchmarks/phase-g-v1`, `benchmarks/loss-v1` and the A-G
suite `benchmarks/ag-v1.12`) was registered during 0.5.9 and removed before the
release. The 16 fixtures and the 16 FEMM records here are those files,
unchanged. The earlier phase left the outer rotor's rotor loss out; this one
includes it.

The specification `benchmark_spec.json` is frozen. `tools/make_phase_g.py`
wrote it and refuses to replace it: a change needs a new protocol folder and
version.
