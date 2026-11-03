# FEMM reference request: cogging torque (#185)

This brief is for the Windows FEMM 4.2 run that gives the proposed cogging
cases their references. The cases and gates are in
[the benchmark proposal](COGGING_BENCHMARK_PROPOSAL.md); the solver settings
behind coilEM's side are in [the convergence study](COGGING_CONVERGENCE.md).
Nothing here changes a registered protocol, gate or record.

## Goal

One FEMM 4.2 no-load torque waveform per case, over one cogging period, at the
angles listed below. The harness compares coilEM's cogging peak-to-peak and
first cogging harmonic with them.

There are two checkpoints where you stop and wait for the owner:

1. after the pilot case, before the full set;
2. after the self-checks, before anything is registered.

## Cases

Each request is a registered fixture with `solve_options.cogging_torque` and
`solve_params.corner_refinement` set to `true`. The second only refines
coilEM's own mesh; the geometry to model is the fixture's. Cogging has no current, so the fixture's phase current does not
enter the cogging waveform; model every winding region with zero current.

| Case | Base fixture | Slots / poles | Cogging period (elec / mech) | Cycles per mech rev |
| --- | --- | --- | --- | --- |
| `spm_8p12s_example_shoed__cogging` | `benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json` | 12 / 8 | 60° / 15° | 24 |
| `ipm_flat_8p12s_fsae_contract__cogging` | `benchmarks/main-20261009-bad71d9/fixtures/ipm_flat_8p12s_fsae_contract.json` | 12 / 8 | 60° / 15° | 24 |
| `spm_8p48s_distributed_femm_validation__cogging` | `benchmarks/main-20261009-bad71d9/fixtures/spm_8p48s_distributed_femm_validation.json` | 48 / 8 | 30° / 7.5° | 48 |
| `ipm_flat_12s10p_fscw_contract__cogging` (optional, low cogging) | `benchmarks/main-20261009-bad71d9/fixtures/ipm_flat_12s10p_fscw_contract.json` | 12 / 10 | 30° / 6° | 60 |

Build each geometry from coilEM's regions, as for the registered cases.
Keep the registered material contract: M350-50A from the suite's B-H curve,
N42 magnets as linear recoil with Br 1.315 T and μr 1.05, the stack length
from the fixture. The tooth shoes of the first case matter more here than for
loaded torque: cogging comes from the slot openings.

## Angles

Solve 25 rotor positions per case: 24 per cogging period plus the repeated
end, in the public clockwise convention (`public-clockwise-v2`) the other
records use. Position *k* is at *k*·period/24, for *k* = 0 … 24.

- 8p/12s cases: 0° to 60° electrical in 2.5° steps, which is 0° to 15°
  mechanical in 0.625° steps.
- 8p/48s case: 0° to 30° electrical in 1.25° steps (0° to 7.5° mechanical in
  0.3125° steps).
- 12s/10p case: 0° to 30° electrical in 1.25° steps (0° to 6° mechanical in
  0.25° steps).

Position 0 is the rotor angle of the registered requests' first position.
The two ends are the same physical position: report both, solved separately.

## Torque extraction

Cogging is a small difference of large stress contributions, so the
extraction method matters more than for mean torque.

- **Preferred:** an air-gap element boundary in the air gap, rotating the rotor
  by the boundary's inner angle, so the gap is not remeshed between positions.
  Report the gap-integral torque.
- **Otherwise:** remesh per position and report the weighted stress tensor
  block integral over the air-gap regions.

Record which one you used, with FEMM's solver precision (1e-8 or tighter),
minimum angle and the mesh size in the air gap.

**One mesh control, please:** solve `spm_8p12s_example_shoed__cogging` a
second time with the air-gap mesh size halved, and report how far its
peak-to-peak and first harmonic move. That gives the reference its own
uncertainty, which the proposal's floor allows for.

## Record

Lay the bundle out like `benchmarks/reference-baselines/ipm-high-output-v3/`.
Each record has the usual identity fields (`case_id`, `phase`, `input_sha256`,
`convention`, `normalized`, `reference_commit`) and in `result`:

```json
"summary": {"cogging_torque_Nm": <peak to peak>},
"cogging_torque_waveform": {
  "electrical_angle_deg": [25 values],
  "mechanical_angle_deg": [25 values],
  "torque_Nm": [25 values]
},
"solve_metadata": {"femm_version": "...", "torque_method": "air_gap_element | weighted_stress_tensor",
                   "precision": 1e-8, "min_angle_deg": 30, "airgap_mesh_size_mm": ..., "mesh_element_count": ...}
```

Replace machine paths with `<local-user-root>`. Every record comes from one
adapter commit, as in protocol 1.6.0.

## Self-checks before hand-off

These check the reference itself, before any comparison with coilEM:

1. **It repeats.** |T(period) − T(0)| is under the absolute floor of the
   proposal for every case.
2. **It averages to zero.** The mean over the 24 positions without the
   repeated end is under the same floor.
3. **The mesh control** moves the peak-to-peak by less than the proposal's
   PASS tolerance.

A failure in 1 or 2 points to a mesh or rotation-bookkeeping problem in the
model, not a difference from coilEM. Fix it before hand-off.

## Hand back

Copy everything to the Mac, in a new folder under `~/coilem-experiments-notes/`:

- the bundle as a zip, with its SHA-256;
- the self-check results and the mesh control;
- the pins: coilEM commit, adapter commit and FEMM binary hashes;
- every failed or retried attempt.

## Rules

- The bundle stays REVIEW_REQUIRED until the owner accepts it. Don't register
  it, add the cases to a benchmark spec, or change any gate or threshold.
- Don't fit, align, interpolate, filter or rescale the FEMM waveforms.
- Don't change coilEM's code. If a fixture or this request looks wrong, stop
  and report.
- The FEMM adapter stays private: no public file, commit or PR names or links it.
- Commits or PRs go out only as `coilemdev`.
