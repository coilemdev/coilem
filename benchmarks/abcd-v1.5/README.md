# A/B/C/D benchmark protocol 1.5.0: a shoed slot

Harness **1.7.0** supports protocol **1.5.0**. The default stays
[protocol 1.4.0](../abcd-v1.4/README.md) until the 0.5.0 freeze
requalification. Until then, 1.5.0 is a separate extension, like the
[1.2.0 Prius extension](../abcd-v1.2/README.md).

Protocol 1.5.0 keeps every 1.4.0 request, golden vector and gate. It adds one
Phase A case, `spm_8p12s_example_shoed`:

- **Geometry.** The app's default example: a 200 mm 8-pole, 12-slot SPM with
  tooth shoes (2.5 mm high, 1.5 mm overhang), 15 turns per coil and two
  parallel paths.
- **Operating point.** 30 A rms, current angle 0°, 2,400 rpm.
- **Grid.** Sampling, mesh and solver settings are those of the registered
  Phase A requests (48 positions over one electrical cycle).

**Why.** Every other registered request has plain slots. A tooth shoe takes
part of the slot, so its winding is smaller than the nominal trapezoid the slot
current density used to be normalised by. The example ran at 95.6% of its
commanded current, and so read 4.4% low on loaded torque. No registered case
could show this. Slot current density now spreads each coil side's
ampere-turns over its own meshed area. This case keeps that covered on a full
solve: the row's energy-balance diagnostic sets the torque against the torque
its own back-EMF and current imply.

**No FEMM parity yet.** The frozen FEMM bundle has no record for this case,
and 1.5.0 claims no bridge to it. Run 1.5.0 with `--no-reference`; the row is
NOT_COMPARED. A FEMM record for the shoed example is the owner's next
reference run. The freeze registers it alongside the A/B/C/D rerun. That FEMM
model must put N·I/paths into each slot's drawn winding, for example through
a circuit with block turns. It must not use a density over the trapezoid area
(the frozen `compute_3phase_current_density` helper), or FEMM would repeat the
shortfall instead of catching it.

## Run it

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.5/benchmark_spec.json \
  --phases A --case spm_8p12s_example_shoed --no-reference --out-dir ../benchmark-output/shoed
```

The other options work as in 1.4.0.
