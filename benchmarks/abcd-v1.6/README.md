# A/B/C/D benchmark protocol 1.6.0: the 0.5.0 reference gates

Harness **1.8.0** supports protocol **1.6.0**. The default stays [protocol 1.4.0](../abcd-v1.4/README.md) until the 0.5.0 freeze. At the freeze, the owner's FEMM bundle for 1.6.0 arrives and this suite becomes the default.

Protocol 1.6.0 keeps every 1.4.0 request, golden vector and gate unchanged. It adds 17 cases, all derived from registered requests:

| Cases | Phase | What is new |
| --- | --- | --- |
| `spm_8p12s_example_shoed` | A | The app's shoed example, as registered in [protocol 1.5.0](../abcd-v1.5/README.md). |
| `spm_8p12s_concentrated__magnet_{60,100}C` | A | The 8p12s concentrated baseline with N42 magnets at 60 °C and 100 °C (Br 1.25188 T and 1.18876 T). |
| `ipm_flat_8p12s_fsae_contract__magnet_{60,100}C` | B | The FSAE flat IPM with N42 magnets at 60 °C and 100 °C. |
| `spm_8p12s_concentrated__dq_I{20,40}_g{0,30,60}` | A | Loaded λd and λq at 20 and 40 A peak (1× and 2× the baseline current), at γ 0°, 30° and 60°. |
| `ipm_flat_8p12s_fsae_contract__dq_I{50,100}_g{0,30,60}` | B | Loaded λd and λq at 50 and 100 A peak (1× and 2×), at γ 0°, 30° and 60°. |

Each temperature fixture differs from its base request only in `solve_params.magnet_temperature_C`. Each d/q fixture differs only in `current_amplitude_A` and `current_angle_deg`. The tests check both.

## Gates

- **Every new case** carries the usual A/B gates against FEMM: mean torque (8% / 15%), Back-EMF fundamental and peak (10% / 15%), torque method, native mesh and angle grids.
  - The temperature cases test the Br derating: FEMM models the derated Br as registered on each case.
  - The shoed case tests the slot-current fix.
- **The d/q points** (`"dq_reference": true`) add three gates (`backend/benchmark_suite/dq_metrics.py`):
  - **`lambda_d`, `lambda_q`:** the candidate's loaded λd and λq against the reference's. The error is a share of the reference's |λdq|: PASS ≤ 3%, YELLOW ≤ 6%.
    - The flat IPM and SPM cases already agree with FEMM within 0.7% on torque and 0.6% on Back-EMF, so 3% leaves room for load saturation without hiding a convention error.
  - **`reference_dq_torque`:** the reference's own d/q torque, 1.5·P·(λd·iq − λq·id), against its solved torque: PASS ≤ 2%, YELLOW ≤ 5%. This catches a convention or bookkeeping slip on the reference side.
  - The harness computes the reference's λd and λq from its raw per-position waveforms with coilEM's own transform. The candidate and the reference therefore cannot differ by convention: amplitude-invariant Park, d-axis fitted from the no-load flux linkage, positions averaged.

A case's status is the worst of its gates, and missing data makes it INCOMPLETE.

## Reference

There is no FEMM record yet for any new case. 1.6.0 needs its own bundle: protocol `1.6.0`, all 46 supported records at one adapter commit. See [FEMM-REQUEST.md](FEMM-REQUEST.md) for what to produce. Until then, run it with `--no-reference`. The new rows are NOT_COMPARED and the other 30 are not compared either.

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.6/benchmark_spec.json --no-reference --out-dir ../benchmark-output/v1.6
```
