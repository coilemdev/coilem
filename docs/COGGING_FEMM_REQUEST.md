# FEMM reference request: cogging torque (#185)

This brief is for the Windows FEMM 4.2 run that gives Phase E, the cogging
benchmark, its references. The 12 requests and their gates are registered as
a proposal in [protocol 1.7.0](../benchmarks/abcd-v1.7/README.md), with the
reasoning in [the benchmark proposal](COGGING_BENCHMARK_PROPOSAL.md); the
solver settings behind coilEM's side are in
[the convergence study](COGGING_CONVERGENCE.md). Nothing here changes a
registered protocol, gate or record.

## Goal

One FEMM 4.2 no-load torque waveform per case, over one cogging period, at the
angles listed below. The harness compares coilEM's cogging peak-to-peak and
first cogging harmonic with them.

There are two checkpoints where you stop and wait for the owner:

1. after the pilot case, `spm_8p12s_example_shoed__cogging`, before the other 11;
2. after the self-checks, before anything is registered.

## Cases

The requests are the 12 fixtures in `benchmarks/abcd-v1.7/fixtures/`. Each is
a registered protocol 1.6.0 request with `solve_options.cogging_torque` and
`solve_params.corner_refinement` set to `true`. The second only refines
coilEM's own mesh; the geometry to model is the fixture's. Cogging has no
current, so model every winding region with zero current.

| Case | Base request | Slots / poles | Cogging period (elec / mech) | Cycles per mech rev |
| --- | --- | --- | --- | ---: |
| `spm_4p12s_simple__baseline__cogging` | `spm_4p12s_simple__baseline` | 12 / 4 | 60° / 30° | 12 |
| `spm_4p12s_simple__tight_airgap__cogging` | `spm_4p12s_simple__tight_airgap` | 12 / 4 | 60° / 30° | 12 |
| `spm_8p12s_concentrated__baseline__cogging` | `spm_8p12s_concentrated__baseline` | 12 / 8 | 60° / 15° | 24 |
| `spm_8p12s_concentrated__tight_airgap__cogging` | `spm_8p12s_concentrated__tight_airgap` | 12 / 8 | 60° / 15° | 24 |
| `spm_8p12s_example_shoed__cogging` | `spm_8p12s_example_shoed` | 12 / 8 | 60° / 15° | 24 |
| `ipm_flat_8p12s_fsae_contract__cogging` | `ipm_flat_8p12s_fsae_contract` | 12 / 8 | 60° / 15° | 24 |
| `ipm_flat_8p12s_fsae_angled_pocket_contract__cogging` | `ipm_flat_8p12s_fsae_angled_pocket_contract` | 12 / 8 | 60° / 15° | 24 |
| `ipm_flat_12s10p_fscw_contract__cogging` | `ipm_flat_12s10p_fscw_contract` | 12 / 10 | 30° / 6° | 60 |
| `ipm_flat_24s16p_industrial_contract__cogging` | `ipm_flat_24s16p_industrial_contract` | 24 / 16 | 60° / 7.5° | 48 |
| `spm_8p24s_distributed_femm_validation__cogging` | `spm_8p24s_distributed_femm_validation` | 24 / 8 | 60° / 15° | 24 |
| `spm_8p48s_distributed_femm_validation__cogging` | `spm_8p48s_distributed_femm_validation` | 48 / 8 | 30° / 7.5° | 48 |
| `spm_12p36s_distributed_femm_validation__cogging` | `spm_12p36s_distributed_femm_validation` | 36 / 12 | 60° / 10° | 36 |

### Request hashes

Each record's `input_sha256` binds it to its request: the SHA-256 of the
fixture as canonical JSON (`backend.benchmark_suite.contract.canonical`).
`benchmark_spec.json` holds the same numbers; check each fixture file's
SHA-256 first, and if either differs, stop and report.

| Case | Fixture SHA-256 | Request `input_sha256` |
| --- | --- | --- |
| `spm_4p12s_simple__baseline__cogging` | `0133baad78c3025ad988889004d0bfadd44afa0c184daf2a5a0ed8e0ca7b87c1` | `8839611fad28d21d9b088c0450e8272e9841fb2349f239cba2656f20bd7aa293` |
| `spm_4p12s_simple__tight_airgap__cogging` | `7b8df6177db2310fc8747da7afe5ab1dd568a6bbfe86f6011fb1c15b97f0d045` | `3c1b57c0bb3b063419cc0944252d0d2c19efba99b24e2f0175c0139f63318a29` |
| `spm_8p12s_concentrated__baseline__cogging` | `228bfe80718719ef811ca8d9e22e78e03f87cd23eabe9c6af8648b25dde6fc61` | `345b5167e28a6be168cb1064089aa00b6055f27a040307bbf54bfca853f42691` |
| `spm_8p12s_concentrated__tight_airgap__cogging` | `4fea72c749da4156d9eed4e3548759f3420c23d4ad1fe5dce09f0f8d288b0701` | `6327927a94e5d3381b69d2975019161a9eebe7944b6f0514bb29cc5c751fb7c4` |
| `spm_8p12s_example_shoed__cogging` | `183a686cdbdcfcac623f5a9877fb43c9cb9e273657e947c14b097f8de9d52c9c` | `9d468051d18b1ca9936d11057924e365b81aedadf14892c21aaed9a203bc619d` |
| `ipm_flat_8p12s_fsae_contract__cogging` | `ec1ca45e0258ca76d072503a3160260377a57a1402b8161bd0952d8fad46bc0a` | `bc4148dc2f8a60bf0fab4033d050883a4bc5718662ad1fb93ef3bd567c5efac4` |
| `ipm_flat_8p12s_fsae_angled_pocket_contract__cogging` | `9ea0820bfe9507ed339415a49b66f207f994392d7172c9cc9f68793197e8af3c` | `4f4686dcf06b28586ff750d384bf6f64d8d5cca83e8d110b4366f5198f188d96` |
| `ipm_flat_12s10p_fscw_contract__cogging` | `b8ec65a0f26330a9f1e9e9829e6ec34752771678fc8dcdcf0789b9074a623fda` | `727e2f8a47115811f9a96a63ddd3fea44439af4ed134d4588c28657b0f6c5ebb` |
| `ipm_flat_24s16p_industrial_contract__cogging` | `9db76e873718646ce320302b39c25301ef3915375cf91ed6489b07f68d53ea5f` | `683373683bee02043cd55a62b3d95da0af3e31625f8cd5cddc3d84f39eefa4d8` |
| `spm_8p24s_distributed_femm_validation__cogging` | `7e1329e2eece8c1c7b23b0b7e862c82a3c659fced4b99b795238c4679ea3e15c` | `691e3d6dac30f855614acf981bb81e59b4832ca24872716fe2f8e671bb09ef87` |
| `spm_8p48s_distributed_femm_validation__cogging` | `851e55cebd81733996d8549f9153d2e9998b55094cc4e6332ae76cf1f76ebac1` | `0e3e1ac40c748c83d1c996daf90ab6ae0ea4fdedb832331faeb1d35f5aa72f23` |
| `spm_12p36s_distributed_femm_validation__cogging` | `4e27491c2d31ea3119a3034bbcda330c016db340aab51d9f3044686ef0bfdfd8` | `a2c3bfb257ac11398802ae8e347846e7f816ab78284411066784a7540c89a9e7` |

```python
import json
from backend.benchmark_suite.contract import canonical

print(canonical(json.load(open(fixture_path, encoding="utf-8"))))
```

Build each geometry from coilEM's regions, as for the registered cases.
Keep the registered material contract: M350-50A from the suite's B-H curve,
N42 magnets as linear recoil with Br 1.315 T and μr 1.05, the stack length
from the fixture. Slot openings, tooth shoes and the IPM pockets matter more
here than for loaded torque: cogging comes from them.

## Angles

Solve 25 rotor positions per case: 24 per cogging period plus the repeated
end, in the public clockwise convention (`public-clockwise-v2`) the other
records use. Position *k* is at *k*·period/24, for *k* = 0 … 24, with the
period in the table above:

- a 60° electrical period: 0° to 60° in 2.5° steps;
- a 30° electrical period (8p/48s and 12s/10p): 0° to 30° in 1.25° steps.

The mechanical angle is the electrical angle divided by the pole pairs.
Position 0 is the rotor angle of the base request's first position. The two
ends are the same physical position: report both, solved separately.

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

**Two mesh controls, please.** Solve `spm_8p12s_example_shoed__cogging` and
`ipm_flat_12s10p_fscw_contract__cogging` (the lowest cogging) a second time
with the air-gap mesh size halved, and report how far each one's peak-to-peak
and first harmonic move. That gives the reference its own uncertainty, which
the floor allows for.

## Record

Lay the bundle out like `benchmarks/reference-baselines/ipm-high-output-v3/`,
with `protocol_version` `1.7.0` in its manifest.
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

1. **It repeats.** |T(period) − T(0)| is under the case's `cogging_floor_Nm`
   in `benchmark_spec.json`.
2. **It averages to zero.** The mean over the 24 positions without the
   repeated end is under the same floor.
3. **The mesh controls** move the peak-to-peak by less than the PASS
   tolerance, max(10%, floor).

A failure in 1 or 2 points to a mesh or rotation-bookkeeping problem in the
model, not a difference from coilEM. Fix it before hand-off.

## coilEM's side (optional, if the VM has time)

coilEM's own values for these requests are still missing (the measuring
Mac ran out of disk). On the VM, at this branch's head, run the suite natively:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.7/benchmark_spec.json --no-reference --out-dir <out>\v1.7-phase-e-native
```

These are native values for review, not a benchmark record.

## Hand back

Hand these to the owner, outside the public repository:

- the bundle as a zip, with its SHA-256;
- the self-check results and the mesh control;
- the pins: coilEM commit, adapter commit and FEMM binary hashes;
- every failed or retried attempt.

## Rules

- The bundle stays REVIEW_REQUIRED until the owner accepts it. Don't register
  it, change the Phase E requests, or change any gate, floor or threshold.
- Don't fit, align, interpolate, filter or rescale the FEMM waveforms.
- Don't change coilEM's code. If a fixture or this request looks wrong, stop
  and report.
- The FEMM adapter stays private: no public file, commit or PR names or links it.
- Commits or PRs go out only as `coilemdev`.
