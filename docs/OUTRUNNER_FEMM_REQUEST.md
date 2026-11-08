# FEMM reference request: outer-rotor motors (Phase F)

This brief is for the Windows FEMM 4.2 run that gives Phase F, the outer-rotor
benchmark, its references. The 10 requests and their gates are registered as
a proposal in [protocol 1.8.0](../benchmarks/abcd-v1.8/README.md); the
outer-rotor conventions are in [OUTRUNNER.md](OUTRUNNER.md). Nothing here
changes a registered protocol, gate or record.

## Goal

One FEMM 4.2 record per case, like a Phase A record: the loaded torque
waveform and the no-load phase back-EMF over one electrical cycle. The harness
compares coilEM's mean torque, back-EMF fundamental and back-EMF peak with
them, using Phase A's gates.

There are three checkpoints where you stop and wait for the owner:

1. after the [LRK check](#before-the-pilot-the-lrk-check), before the pilot;
2. after the pilot case, `spm_outer_14p12s_drone__baseline`, before the other 9;
3. after the self-checks, before anything is registered.

Outer rotors are new to the adapter, so the LRK check and the pilot are where
the model is set up. Expect them to take longer than the other nine together.

## Cases

The requests are the 10 fixtures in `benchmarks/abcd-v1.8/fixtures/`. Each is
the registered Phase A request `spm_8p12s_concentrated__baseline` with an
outer-rotor SPM motor and the case's current; the
[suite README](../benchmarks/abcd-v1.8/README.md#cases) lists the motors.

| Case | Fixture SHA-256 | Request `input_sha256` |
| --- | --- | --- |
| `spm_outer_14p12s_drone__baseline` | `d28c5ba8c5f9ac8cf0f76118dd23b3a66381b6a94422375e174481d590dbebfd` | `98f97b633efdb1c608eb29e1073dfa37a3243289c9b28a89ebe3cb40ea57a796` |
| `spm_outer_14p12s_drone__high_current` | `e6106404b824cfeda9cab9c3b4d3a2ec3949af136a34d0fbe9555a778be8c90a` | `da3ae311455cca6f9afff1b5655387ebb8227c08b7c1c99abbf35dce919fac3e` |
| `spm_outer_14p12s_drone__tight_airgap` | `45bbfeba9932c336fc03e4885e0315b7333edbae9f41fb1974bcba1459e0a55c` | `573525d1deca8d243b5f13b934d0fd5d7c590b27169d715fbe6ebf6e1df0a4c0` |
| `spm_outer_14p12s_drone__angle30` | `8dd6530c8fca36c7d52254339129fe2659fed94d9a9401808377ac6b7bea54c6` | `1b951c9fec95551201d8d7a953a7c547cfba9a37ec83963fdf28388c174aba1f` |
| `spm_outer_14p12s_drone_noload__baseline` | `bb2f627bb4b994abd920bcb80eca31e2839b6c760b229cb632ba08102b8f7e6b` | `527dad6d6004ef7142c5f59229383d000e0fcda6f13e7b2d92a3ad153d4a417e` |
| `spm_outer_12p9s_micro__baseline` | `16a3f9b8a0c46ef1863b122442c45382ad68574aa4f41a56087c66f261979e60` | `1f2914b021a10e086ff935e099bfbe465a5f41b20ca2caf194ca307d15ee9b6e` |
| `spm_outer_12p9s_micro_noload__baseline` | `1f89b16e826a94c88bbeccbfc42a4a1f329d51888b8f85eb9f8b608624cfe166` | `33a2b4107a19a39472caf05aa4317d6db3a167d2e6ffa937086801101dd96b25` |
| `spm_outer_10p12s_single_layer__baseline` | `37828c63a82cad9c8ec31d15cd482b43fa59aec806efef62dfcacb88cabd20e5` | `0bf442ea05afbe40b2596646d9c35396f4da44d2b5d3e8c7fb6cb0b6a67b1e13` |
| `spm_outer_28p24s_multirotor__baseline` | `fea87e2a6e905823d319d4de7875d3e70f16c77bfe12503f5f6f7f03ebfa1021` | `dc7bf197240fe1348fba0f3a5a00e85d7b180ee68fb86358ef0e0626fd133633` |
| `spm_outer_30p27s_hub__baseline` | `a96e7da3ada0179da00f5aa83b8ef120173633e8fef482a8ac5cce435911f1c5` | `fbd133c5d3863f5364c5fb3bc22e860ec3793fd0340cb054de0eb3209e2733b5` |

Each record's `input_sha256` binds it to its request: the SHA-256 of the
fixture as canonical JSON (`backend.benchmark_suite.contract.canonical`).
`benchmark_spec.json` holds the same numbers. Check each fixture file's
SHA-256 first, and if either differs, stop and report.

## The outer-rotor model

Build each geometry from coilEM's regions at this branch's head
(`backend.geometry_ir.build_geometry_ir`), as for the registered cases. The IR
says it is an outer rotor (`rotor_layout` `"outer"`, metadata `radial_layout`
`"outer_rotor"`). What differs from the inner rotors the adapter already
models:

- **Field meanings.** `stator.OD_mm` is the air-gap face (the tooth tips),
  `stator.ID_mm` the hub bore, `rotor.ID_mm` the magnet seat (the back-iron
  ring's inner face) and `rotor.OD_mm` the ring's outer face. The magnets sit
  on the inside of the ring.
- **Boundary.** A = 0 on two circles: the rotor OD and the hub bore. The IR
  tags both curves `dirichlet_az_zero`. Nothing inside the hub bore is
  modelled. Don't put A = 0 on the stator OD: that is the air-gap face here.
- **What moves.** The regions in motion group `rotor`: the ring
  (`RotorCore`), the magnets and the air between them (`MagnetPocketAir`).
  The stator, its slots and the hub stay still.
- **Air gap.** The `Airgap` region, from `airgap_stator_side_radius_mm`
  (inside, the tooth tips) to `airgap_rotor_side_radius_mm` (outside, the
  magnet faces), both in the IR metadata. The stator is the body inside the
  gap.
- **Magnets.** Use each magnet region's magnetization from the IR. Pole 0
  points inward: its north faces the air gap. Polarity alternates.
- **Materials.** The registered contract: M350-50A from the suite's B-H curve
  for the stator and the rotor ring, N42 magnets as linear recoil with
  Br 1.315 T and μr 1.05, and the stack length from the fixture.
- **Tooth shoes.** Four motors have shoed teeth at the stator OD; the 12/10
  single-layer motor has plain teeth. The IR draws each shoe: a wide tip at the
  air-gap face over `tooth_shoe_height_mm`, then the parallel tooth body. Lower
  the tooth and slot regions as given. As for inner stators, the slot region
  includes the shoe neck.
- **Turns.** `winding.turns_per_coil` counts the conductors in one slot, not
  the turns of one coil (`backend/winding_utils.py`). With two layers, two tooth
  coils share each slot, so each coil has half: the drone's 12 is 6 turns per
  coil. The single-layer case and the LRK put all of them in one coil. Taking
  the slot currents from coilEM, as below, gets this right. An adapter that
  builds coils from `turns_per_coil` itself must halve it for two layers, or its
  flux linkage and back-EMF come out double.

## Currents and back-EMF

Take each slot's current from coilEM's winding map and excitation at this
commit, as for the registered cases. The one outer-rotor change: phase A's
flux axis sits 180° electrical further on than for an inner rotor
(`backend/excitation.py`, `phase_axis_offset_deg`). A gap-facing north pole
drives flux inward through an outer rotor's stator. If the adapter derives
currents itself rather than calling coilEM, it must add those 180°.

Check the currents at position 0 against coilEM's, in the public convention:

| Case | Peak current, γ | Phase A axis | i_A (A) | i_B (A) | i_C (A) |
| --- | --- | ---: | ---: | ---: | ---: |
| `spm_outer_14p12s_drone__baseline` | 10 A, 0° | 210° | 8.660254 | -8.660254 | 0.000000 |
| `spm_outer_14p12s_drone__high_current` | 15 A, 0° | 210° | 12.990381 | -12.990381 | 0.000000 |
| `spm_outer_14p12s_drone__tight_airgap` | 10 A, 0° | 210° | 8.660254 | -8.660254 | 0.000000 |
| `spm_outer_14p12s_drone__angle30` | 10 A, 30° | 210° | 10.000000 | -5.000000 | -5.000000 |
| `spm_outer_12p9s_micro__baseline` | 5 A, 0° | 210° | 4.330127 | -4.330127 | 0.000000 |
| `spm_outer_10p12s_single_layer__baseline` | 15 A, 0° | 225° | 10.606602 | -14.488887 | 3.882286 |
| `spm_outer_28p24s_multirotor__baseline` | 10 A, 0° | 210° | 8.660254 | -8.660254 | 0.000000 |
| `spm_outer_30p27s_hub__baseline` | 20 A, 0° | 210° | 17.320508 | -17.320508 | 0.000000 |

The axis column includes the outer rotor's 180°. The two no-load cases carry no current. The values come from
`backend.excitation.resolve_phase_current_sample(config, 0.0, clockwise_positive=True)` at this commit.

**Reviewed execution note (2026-11-08).** The table above preserves the
original brief's direct-helper convention. The completed Windows collection
uses the unchanged v0.5.5 production solver convention, as the owner approved:
`backend.solver._clockwise_excitation_config` reflects the excitation angle
as `180° − γ`, and the native rotor position is `−θ`. For the drone baseline
at position zero this gives `(−8.660254, +8.660254, 0)` A. The angle-30° and
single-layer cases require the same production mapping; simply negating
every table entry is not a general conversion. The
[reviewed Windows packet](../benchmarks/windows-v055-phase-f-20261108/README.md)
records the production drive choice. No fixture or registered gate was
changed to make the comparison pass.

The back-EMF is the no-load phase voltage from dλ/dt at the fixture's
3000 rpm, with coilEM's winding signs, as for Phase A.

## Angles

48 rotor positions per case, 0° to 352.5° electrical in 7.5° steps, in the
public clockwise convention (`public-clockwise-v2`) the other records use.
This applies to both the loaded torque and the no-load back-EMF. The
mechanical angle is the electrical angle divided by the pole pairs (7, 6, 5,
14 and 15 for the five motors).

## Torque

**Report the rotor's torque, positive clockwise**, as for the inner-rotor
records. Most torque shortcuts give the torque on the body inside the air
gap, which here is the stator:

- a weighted stress tensor block integral over the stator's blocks;
- FEMM's air-gap element or gap integral.

Negate those. A block integral over the rotor's own blocks needs no sign
change. Use the same method, solver precision (1e-8) and minimum angle (30°)
as the adapter's Phase A records, and record which you used.

**The gates compare mean torque with its sign**, so a stator torque fails
every loaded case at about 200%. The self-checks below catch it first.

**Mesh.** These motors are small: the air gap is 0.25–0.5 mm, and the
smallest stator is 18 mm. Make sure the air gap has at least three elements
across, and record the air-gap mesh size and the element count.

**Two mesh controls, please.** Solve `spm_outer_12p9s_micro__baseline` and
`spm_outer_14p12s_drone__tight_airgap` a second time with the air-gap mesh
size halved. Report how far each one's mean torque and back-EMF fundamental
move.

## Before the pilot: the LRK check

The LRK 12-slot / 14-pole outrunner is FEMM's own sliding-band benchmark. Its
[example page](https://www.femm.info/wiki/SlidingBandBenchmark) publishes the
torque, and coilEM carries the geometry as a pinned reference. Running the LRK
through the adapter checks the adapter's outer-rotor model against FEMM's own
solution before any coilEM number is involved. If it matches, the boundary,
the moving body, the currents and the torque sign are right. It uses no coilEM
result, so the Phase F run stays blind.

- **Model.** Build the IR from the pinned config
  `backend/reference_models/lrk_12s14p_config.json` (`geometry_reference`
  `lrk_12s14p`). coilEM lowers it from the hash-checked drawing
  `lrk_12s14p_source.json`, the benchmark's `WholeMotor.fem`.
- **Materials.** Use the config's own materials, not the Phase F contract:
  - its two `custom_steels`, M-19 with the lamination fill folded into the
    curve, and 1018;
  - `LRK_NdFeB_40MGOe` magnets, Br 1.29053 T and μr 1.049.

  The stack is 10 mm, with 15 conductors per slot in a single layer: 15 turns
  per coil.
- **Coordinates.** coilEM turns the source stator +15° and relabels circuits
  B and C, so the winding is the generic 12s/14p map. Solve published position
  θ at coilEM rotor angle θ + 15° (`build_geometry_ir`'s counter-clockwise
  `rotor_angle_deg`). Drive the published currents A/B/C as generic A/C/B; the
  table lists both.
- **Torque.** The page reports the outer rotor's torque, counter-clockwise
  positive, from its physical-rotation weighted stress tensor. Report the
  rotor's torque clockwise positive, as for Phase F. The expected value is the
  published one negated.

| Position θ | Published A / B / C (A) | Generic A / B / C (A) | Published (mN·m, CCW) | Expected (mN·m, rotor CW) |
| --- | --- | --- | ---: | ---: |
| −1/7° | 0 / 4 / −4 | 0 / −4 / 4 | −57.7303 | +57.7303 |
| 0° | 0 / 4 / −4 | 0 / −4 / 4 | −55.4274 | +55.4274 |
| +1/7° | 0 / 4 / −4 | 0 / −4 / 4 | −53.5645 | +53.5645 |
| 5° | 0 / 4 / −4 | 0 / −4 / 4 | −37.6901 | +37.6901 |
| 20° | 0 / 4 / −4 | 0 / −4 / 4 | +33.6738 | −33.6738 |
| 40° | 0 / 4 / −4 | 0 / −4 / 4 | −3.3944 | +3.3944 |
| 0° | 0 / −6 / 6 | 0 / 6 / −6 | +82.9159 | −82.9159 |
| 0° | 0 / −2 / 2 | 0 / 2 / −2 | +27.6362 | −27.6362 |
| 0° | 0 / 2 / −2 | 0 / −2 / 2 | −27.7659 | +27.7659 |
| 0° | 0 / 6 / −6 | 0 / −6 / 6 | −83.0470 | +83.0470 |
| 0° | 0 / 0 / 0 | 0 / 0 / 0 | −0.0649 | +0.0649 |

Pass each point within max(2%, 0.05 mN·m), the rule coilEM's own LRK
acceptance used. A miss on any point above 20 mN·m points to the adapter's
outer-rotor model (boundary, moving body, current mapping or torque body), so
fix it before the pilot. The 40° and zero-current points are under 4 mN·m,
where mesh noise alone can exceed 0.05 mN·m: report them either way.

## Record

Lay the bundle out like
`benchmarks/reference-baselines/protocol16-reviewed-20261103/`, with
`protocol_version` `1.8.0` and `suite_sha256` the SHA-256 of
`benchmarks/abcd-v1.8/benchmark_spec.json` in its manifest. Each record has
the usual identity fields (`case_id`, `phase` `"F"`, `input_sha256`,
`convention`, `normalized`, `reference_commit`, `public_candidate_commit`).
Its `result` holds what a Phase A record holds:

```json
"summary": {"avg_torque_Nm": ..., "back_emf_fundamental_V": ...},
"torque_waveform": {"electrical_angle_deg": [48 values], "torque_Nm": [48 values]},
"back_emf_waveform": {"electrical_angle_deg": [48 values], "phase_a_V": [...], "phase_b_V": [...], "phase_c_V": [...]},
"solve_metadata": {"femm_version": "...", "torque_method": "...", "torque_body": "rotor | stator (negated)",
                   "precision": 1e-8, "min_angle_deg": 30, "airgap_mesh_size_mm": ..., "mesh_element_count": ...}
```

`back_emf_fundamental_V` is the RMS fundamental of phase A, as in the Phase A
records. Replace machine paths with `<local-user-root>`. Every record comes
from one adapter commit.

## Self-checks before hand-off

These check the reference itself, before any comparison with coilEM. They use
only FEMM's own numbers:

1. **Sign.** The mean torque is positive in every loaded case.
2. **Energy balance.** Mean torque against 3·E·I·cos γ / ω, with E the RMS
   back-EMF fundamental, I the RMS current and ω the mechanical speed. Expect
   within 5% for the baselines; it reads lower under saturation (the
   1.5 × current case). A ratio near 2 or 0.5 points to a winding or
   flux-linkage factor, as in public issue 80.
3. **Current angle.** The 30° case's mean torque over the drone baseline's is
   0.80–0.90; an SPM gives about cos 30° = 0.87.
4. **Balance.** Phases B and C have back-EMF fundamentals within 1% of A's,
   120° apart.
5. **No load.** The two no-load cases' mean torque is under 1% of their
   loaded baseline's.
6. **Mesh controls.** Each control moves mean torque and back-EMF
   fundamental by less than 2%.

A failure in 1–4 points to the outer-rotor model (boundary, moving body,
torque body or phase axis), not a difference from coilEM. Fix it before
hand-off.

## coilEM's side (optional, if the VM has time)

At this branch's head, run the suite natively on Windows:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.8/benchmark_spec.json --no-reference --out-dir <out>\v1.8-phase-f-native
```

These are native values for review, not a benchmark record. Keep them out of
the FEMM run until the bundle is handed back, so the reference stays blind.

## Hand back

Hand these to the owner, outside the public repository:

- the bundle as a zip, with its SHA-256;
- the LRK check's 11 torques, with their mesh settings;
- the self-check results and the mesh controls;
- the pins: coilEM commit, adapter commit and FEMM binary hashes;
- every failed or retried attempt, including the pilot's set-up attempts.

## Rules

- The bundle stays REVIEW_REQUIRED until the owner accepts it. Don't register
  it, change the Phase F requests, or change any gate or threshold.
- Don't fit, align, interpolate, filter or rescale the FEMM waveforms.
- Don't change coilEM's code. If a fixture or this request looks wrong, stop
  and report.
- The FEMM adapter stays private: no public file, commit or PR names or links it.
- Commits or PRs go out only as `coilemdev`.
