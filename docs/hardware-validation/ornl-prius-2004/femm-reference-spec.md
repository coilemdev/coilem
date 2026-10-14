# FEMM reference for the ORNL Prius benchmark case

This is item 5 of [#82](https://github.com/coilemdev/coilem/issues/82): what the owner's FEMM run must produce so that the Prius row in [protocol 1.2.0](../../../benchmarks/abcd-v1.2/README.md) gets matched FEMM parity gates, like every other A/B/C row. The FEMM adapter is private; nothing here needs it to be published.

The owner decided to run this after #80's corrected FEMM data lands, so it does not disturb that run.

## The request

Model exactly the registered request: case `ornl_prius_2004_ipm` in `benchmarks/abcd-v1.2/benchmark_spec.json`, fixture `benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json`. Its `input_sha256` binds the FEMM record to these inputs. The harness refuses a record for any other request.

## Geometry

Build the FEMM model from coilEM's own geometry for the request, as the existing records do; they say `region_source: native_generated_mesh`:

- **Rotor:** `ipm_topology` `pyleecan_holem50`, a connected V per pole. `backend.geometry_drawer.compute_geometry(config)` returns:
  - 16 magnet polygons (`magnets[i].corners_mm`) with `magnetization_angle_deg` and polarity;
  - 24 air-pocket polygons (`rotor_air_pockets[i].corners_mm`), three per pole.

  Rotor OD 160.38 mm, ID 110.64 mm.
- **Stator:** tapered teeth with tooth shoes, from `backend.geometry_ir.build_geometry_ir(config)`.
  - The `StatorTooth`, `StatorYoke` and `SlotWinding` regions.
  - Shoe height 1.02 mm; mouth 1.94 mm.

The public request check rejects HoleM50. Parse the request with `parse_public_solve_request(config, allow_experimental_rotors=True)`, which the harness does for this case. If the adapter dispatches on `ipm_topology`, it needs a `pyleecan_holem50` branch that uses the polygons above. Check this first: an adapter that consumes the generated regions may need no geometry change at all.

## Materials, winding and excitation

All as registered, with nothing tuned to ORNL's measurements:
- **Steel:** M350-50A, both cores, curve SHA-256 `d6096df7…896c3d`, the same as every other case.
- **Magnets:** `ORNL_Prius_2004_NdFeB`, linear recoil, Br 1.235 T, μr 1.12.
- **Winding:** distributed, single layer, full pitch, 9 turns per coil, 1 parallel path; 48 slots, 8 poles, stack 83.82 mm.
- **Excitation:**
  - Loaded: 250 A peak, sinusoidal, current angle 45°, the same convention as the other Phase C cases.
  - Speed: 3,000 rpm for Back-EMF.

## Record

Use the same format as the existing records, for example `spm_8p24s_distributed_femm_validation.json` in `ipm-high-output-v1`:

- `case_id` `ornl_prius_2004_ipm`, `phase` `C`, the request's `input_sha256`, `convention` `public-clockwise-v2`, `normalized` `true`, `reference_commit`.
- `result.summary`: `avg_torque_Nm` and `back_emf_fundamental_V`.
- `result.torque_waveform`: 13 points at 0–90° electrical in 7.5° steps.
- `result.back_emf_waveform`: `phase_a_V`, `phase_b_V` and `phase_c_V` at 48 points over one electrical cycle.
- `result.solve_metadata`, including the FEMM mesh element count.
- Machine paths replaced by `<local-user-root>`.

## Bundle

Protocol 1.2.0 needs its own bundle, because the harness checks that the bundle's protocol and material contract match the suite:
- `protocol_version` `1.2.0`;
- `material_contract` equal to the suite's, including the ORNL magnet;
- 30 records: the 29 from #80's corrected data set plus the Prius.

**Open item for the owner:** the harness requires every record's `reference_commit` to equal the bundle's. If the Prius runs on a later adapter commit than the 29 #80 records, either:
- re-run all 30 at one adapter commit; or
- let the bundle carry a reference commit per record (a small harness change).

## Self-check before hand-off

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.2/benchmark_spec.json \
  --reference-bundle <new bundle> --phases C --case ornl_prius_2004_ipm \
  --out-dir ../benchmark-output/prius-femm-check --pdf
```

The Prius row should then show the usual FEMM gates: mean torque, Back-EMF fundamental and peak, torque method, native mesh and angle grids. It also keeps the exploratory ORNL correlation, which has no verdict.
