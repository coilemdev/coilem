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
the registered Phase A request `spm_8p12s_concentrated__baseline` of protocol
1.9.0 with an outer-rotor SPM motor and the case's current; the
[suite README](../benchmarks/abcd-v1.8/README.md#cases) lists the motors.

**Newton since v0.5.6.** These requests now use Newton, coilEM's default nonlinear method. All ten were regenerated from protocol 1.9.0's Phase A template on 2026-11-09, so only `solve_params.nonlinear_solver` changed, from `picard` to `newton`, and with it the hashes below. FEMM never reads that field. A FEMM record collected against the earlier Picard request hash is still valid for the Newton request, and is registered through a hash-bound solve-option bridge (`reference_compatibility.solve_option_change`, as protocol 1.9.0 does) rather than collected again.

| Case | Fixture SHA-256 | Request `input_sha256` |
| --- | --- | --- |
| `spm_outer_14p12s_drone__baseline` | `33331e3c477f8ab42b802c7504329d397bd169797bbb91a93b0660945a06f96b` | `42899371bf886b6c298d36c73a50cd1099fd8e93e3b46e3703db1657ca9ae66d` |
| `spm_outer_14p12s_drone__high_current` | `34dfd910ae330ea713689fd96fffb8c05ebee9d2e38b7f52fba4018a3514a435` | `eef1807fdc9e3ada58587a88a4275c1fdeb31c9f06bec67030bad564fe8bff8b` |
| `spm_outer_14p12s_drone__tight_airgap` | `86fa0b1dd73f499307871174c140fc43bd8223073360d88e6eeb45f9ad57630d` | `fde301b1d42714255f674e643027ff331fc7084a7db1f1a7a703a5907bc2888e` |
| `spm_outer_14p12s_drone__angle30` | `db1cb043f057a5c5bd6bffe771ea7c66e9d95fb64b4e01a5fa1fc4f0aafebe5e` | `b03bf9f6e5cf23b0611eeb55cde6862e343006a63b926875129423241e4abd96` |
| `spm_outer_14p12s_drone_noload__baseline` | `207ce0028af8c6c1567f545d969c2b6239574363b0a587c8047a05a815b889ed` | `547ebf9bcb3ea42953e617a4534eae707cc998873397d666751ffb3886d505e3` |
| `spm_outer_12p9s_micro__baseline` | `eab9a306c0e63e2e0ac14044baf4ab488ca78304161248d4ef3ed89aa817ec46` | `e3462f15aada4dfaf7d7320e97cd3f831d047e9176dbc10890b2e9370b28ea25` |
| `spm_outer_12p9s_micro_noload__baseline` | `baa532b5817af911fb81e971d9ba2a106403ce76e311bbd711780bee2dfce147` | `a357dd0c03e7b5689c2c76122e2e9e0b8c60c4d8f5c6ebf4b4456e325098f5e5` |
| `spm_outer_10p12s_single_layer__baseline` | `a568e1df4c89caa69eae57e02611549235d9888d1d4af944460237ec3d535a07` | `ac93f5d6954d818321f20e3781a0dc3165e7d2c977938c18feab530bf707d9db` |
| `spm_outer_28p24s_multirotor__baseline` | `b0e14af6e83761af75594b94c1385554953336a29cdf6652a24aa2b56ec3ac70` | `aa309ebcee4b48306c085fc794add7d04b9be06e80b39904e3f7e2de0dd18200` |
| `spm_outer_30p27s_hub__baseline` | `0039a0353e232bf68964bfebe8e2f623184986dffe1075dd3650cf2b5385f983` | `30a730682f9d6f5791174c1a63334728cd6e1a49f08111cbb49af39782d7d457` |

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
