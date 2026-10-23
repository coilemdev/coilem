# FEMM reference request for protocol 1.6.0 (0.5.0 freeze)

This is what the owner's Windows FEMM run must produce for [protocol 1.6.0](README.md):
- the 30 registered 1.4.0 requests;
- 17 new requests, for the shoed slot, magnet temperature and loaded λd/λq.

The FEMM adapter is private, and nothing here needs it published.

## What to hand back

One bundle, in the same layout as `benchmarks/reference-baselines/ipm-high-output-v3/`:

- `manifest.json`:
  - schema `coilem.frozen_reference_bundle/v1`;
  - `protocol_version` `1.6.0`;
  - `convention` `public-clockwise-v2`;
  - `normalized` `true`;
  - one `reference_commit`;
  - `material_contract` equal to the suite's (unchanged from 1.4.0);
  - `records` mapping each case id to `{file, sha256, input_sha256}`.
- **46 records:** every case in `benchmark_spec.json` except the planned-unsupported `ornl_prius_2004_ipm`. All of them must come from **one adapter commit**, because the harness requires every record's `reference_commit` to equal the manifest's.
- **Each record:**
  - `case_id`, `phase`, the request's `input_sha256`, `convention`, `normalized`, `reference_commit`;
  - `result` with `summary` (at least `avg_torque_Nm` and `back_emf_fundamental_V`), `torque_waveform`, `back_emf_waveform` and `solve_metadata` (FEMM version, mesh element count, precision);
  - machine paths replaced by `<local-user-root>`, as in the v3 records.
  - Phase D records keep the six-step format, with `protocol_sha256` equal to the case's.

The harness binds each record to its request through `input_sha256` and refuses one built for any other input.

## The 30 registered 1.4.0 requests

Re-run them as the v3 bundle did. The Phase D requests are the cap-200 ones, and the Picard cap does not apply to FEMM.

**One check, please, on the six V-shape IPM cases (`ipm_vshape_8p12s_*`).** Since the corrected nonlinear stopping test (public issue 11), coilEM's Back-EMF on five of them rose 4.7–6.6%. They now sit 8.1–8.6% above FEMM, against a 10% gate. For these six:
- record FEMM's solver precision, minimum angle and mesh size;
- run `ipm_vshape_8p12s_baseline_contract` once more at a tighter precision (for example 1e-10) and a finer mesh in the bridges;
- report how far its Back-EMF and torque move.

That separates FEMM's own convergence from a model difference.

## New: the shoed example (1 case)

`spm_8p12s_example_shoed`, fixture `benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json`. This is the app's default 8p12s SPM:
- tooth shoes 2.5 mm high with a 1.5 mm overhang;
- 15 turns per coil, 2 parallel paths;
- 30 A rms (42.43 A peak), γ 0°, 2,400 rpm.

Build the geometry from coilEM's regions as for the other cases. **Each slot must carry exactly N·I/paths.**
- Drive the drawn winding regions through FEMM circuits with block turns.
- **Do not use a current density spread over the nominal trapezoid** (the frozen `compute_3phase_current_density` helper). A shoe takes part of that trapezoid, so this case would be under-driven by 4.4%: exactly the error the case exists to catch.

coilEM's native result for this request is 11.183 N·m.

## New: magnet temperature (4 cases)

These are the base requests with only `magnet_temperature_C` changed. Both motors use N42 (catalogue Br 1.315 T, μr 1.05):

| Case | Base request | Magnet | Br to model |
| --- | --- | --- | --- |
| `spm_8p12s_concentrated__magnet_60C` | `spm_8p12s_concentrated__baseline` | 60 °C | 1.25188 T |
| `spm_8p12s_concentrated__magnet_100C` | `spm_8p12s_concentrated__baseline` | 100 °C | 1.18876 T |
| `ipm_flat_8p12s_fsae_contract__magnet_60C` | `ipm_flat_8p12s_fsae_contract` | 60 °C | 1.25188 T |
| `ipm_flat_8p12s_fsae_contract__magnet_100C` | `ipm_flat_8p12s_fsae_contract` | 100 °C | 1.18876 T |

Model the magnets as linear recoil with that Br and μr 1.05 unchanged, so the coercivity scales with Br. The registered Br is also on each case as `magnet_remanence_T`. It is Arnold's reversible coefficient for N42, −0.12 %/°C from 20 °C, which is what coilEM applies. Keep the steel and everything else as in the base request.

## New: loaded λd and λq (12 cases)

These are the base requests with only the current magnitude and angle changed:
- **SPM** (`spm_8p12s_concentrated__dq_I{20,40}_g{0,30,60}`): 20 or 40 A peak.
- **Flat IPM** (`ipm_flat_8p12s_fsae_contract__dq_I{50,100}_g{0,30,60}`): 50 or 100 A peak.
- Each at γ 0°, 30° or 60°.

The current angle follows the convention of the existing `spm_8p12s_reference_angle30__baseline` request: γ is measured from the q-axis toward field weakening, so i_d = −I sin γ and i_q = I cos γ. Use the same mapping the adapter already applies there.

Beyond the usual record, each of these needs three more waveforms in `result`, in the public clockwise convention like the others:

```json
"loaded_flux_linkage_waveform": {"electrical_angle_deg": [...], "phase_a_Wb": [...], "phase_b_Wb": [...], "phase_c_Wb": [...]},
"phase_current_waveform":       {"electrical_angle_deg": [...], "phase_a_A":  [...], "phase_b_A":  [...], "phase_c_A":  [...]},
"no_load_flux_linkage_waveform": {"electrical_angle_deg": [...], "phase_a_Wb": [...], "phase_b_Wb": [...], "phase_c_Wb": [...]}
```

- **Loaded flux linkage:** each phase's total flux linkage at every loaded rotor position, at the positions of `torque_waveform`:
  - the SPM requests use 48 positions over one electrical cycle;
  - the IPM requests use 13 positions over 0–90°.

  This is FEMM's circuit flux linkage. Both motors have one parallel path, so no division is needed: it is the quantity whose time derivative is the phase voltage.
- **Phase currents:** the currents FEMM applied at those same positions. `electrical_angle_deg` must be identical to the loaded one.
- **No-load flux linkage:** the same quantity with zero current, at the positions of `back_emf_waveform`. It places the d-axis.

The harness computes λd and λq from these with coilEM's own transform (`backend/dq_flux_linkage.py`). It then compares them with coilEM's at 3% / 6% of |λdq|.

**Self-check:** it also checks that FEMM's own d/q torque, 1.5·P·(λd·iq − λq·id), reproduces FEMM's `avg_torque_Nm` within 2%. A failure there means a sign, phase-order or angle-reference slip in the waveforms, not a model difference. Run the self-check below before hand-off.

## Self-check before hand-off

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.6/benchmark_spec.json \
  --reference-bundle <new bundle> --out-dir ../benchmark-output/v1.6-femm-check --pdf
```

- Every row should show its gates.
- The d/q rows add `lambda_d`, `lambda_q` and `reference_dq_torque`, and the PDF lists them.
- To check just the new cases first, add `--case <id>` for each.
