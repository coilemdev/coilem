# Coilem A/B/C/D benchmark baseline v1.2

Report v1.2 selects the next-release default matrix: 29 PASS, one planned coverage item (not yet supported). It compiles unchanged October 10 macOS measurements at 45e0a5c with two new October 11 IPM designs at af56962. Each case identifies its actual measured candidate and source evidence. This is not a fresh full run of a single release commit. The planned item is ORNL Prius 2004: its HoleM50 rotor geometry is outside the public flat-buried/V-shape IPM policy. Geometry helpers exist, but native meshing/field solves and matched FEMM qualification are needed before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed and no delivery date is claimed.

Deep apex: magnet legs 9 -> 12 mm; wide angle: 9 -> 10 mm. Both native and FEMM mean torques exceed 0.5 N m. Apex/angle features, current, winding, stack, materials and public numerical defaults are retained. The original low-output cases are removed from the default suite and remain archived with their original FAIL verdicts. Their N m units were correct; displaying mN m does not change relative error. New geometry passing does not fix the original discrepancies.

| Phase | Recorded outcomes |
| --- | --- |
| A - SPM | 10 PASS |
| B - IPM | 12 PASS |
| C - Distributed Winding | 4 PASS, 1 Planned coverage (not yet supported) |
| D - BLDC | 3 PASS; 42/42 gates |

## Comparison policy

Unchanged A/B/C gates: mean torque PASS <=8% / YELLOW <=15%; Back-EMF H1 and peak PASS <=10% / YELLOW <=15%. For reference mean torque below 0.01 N m, absolute torque limits are 0.01 / 0.02 N m. WST, native Gmsh and matched angle grids are required. Signed waveform residuals are diagnostic. Phase D retains fourteen gates per fixture, ideal six-step 120-degree wye and frozen golden currents. Fine refines angular sampling on the same normal spatial mesh; low-current analytical is a native field solve with Back-EMF. Thermal analysis remains outside A/B/C/D. No fitted angle, sign or scale correction is used.

Normal public spatial meshes and numerical defaults. New IPM grids: 13 loaded points at 0-90 degrees and 48 Back-EMF points, step 7.5 degrees.

Orange solid = Coilem / Magneto2D; blue dashed = FEMM. [Full plots and fixture links](coilem_benchmark_report.html).

## Phase A results - SPM

| Fixture input | Outcome | Measured candidate | Metrics |
| --- | --- | --- | --- |
| [spm_4p12s_simple__baseline](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple__baseline__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.478269 / FEMM 0.477514 N m; gap 0.16% (0.000755 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%. |
| [spm_4p12s_simple__high_current](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple__high_current__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.717225 / FEMM 0.716397 N m; gap 0.12% (0.000828 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%. |
| [spm_4p12s_simple__tight_airgap](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple__tight_airgap__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.582697 / FEMM 0.583066 N m; gap 0.06% (0.000370 N m). Back-EMF H1 gap 0.35%; peak gap 0.05%. |
| [spm_4p12s_simple_noload__baseline](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple_noload__baseline__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D -0.000003 / FEMM -0.002058 N m; gap 99.83% (0.002055 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%. |
| [spm_4p12s_simple_noload__high_current](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple_noload__high_current__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.239170 / FEMM 0.238513 N m; gap 0.28% (0.000656 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%. |
| [spm_4p12s_simple_noload__tight_airgap](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_simple_noload__tight_airgap__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D -0.000116 / FEMM -0.000104 N m; gap 12.02% (0.000012 N m). Back-EMF H1 gap 0.35%; peak gap 0.05%. |
| [spm_8p12s_concentrated__baseline](../main-20261010-45e0a5c-rerun/fixtures/spm_8p12s_concentrated__baseline__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 2.561836 / FEMM 2.557786 N m; gap 0.16% (0.004050 N m). Back-EMF H1 gap 0.07%; peak gap 0.15%. |
| [spm_8p12s_concentrated__high_current](../main-20261010-45e0a5c-rerun/fixtures/spm_8p12s_concentrated__high_current__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 3.836667 / FEMM 3.833448 N m; gap 0.08% (0.003219 N m). Back-EMF H1 gap 0.07%; peak gap 0.15%. |
| [spm_8p12s_concentrated__tight_airgap](../main-20261010-45e0a5c-rerun/fixtures/spm_8p12s_concentrated__tight_airgap__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 2.717960 / FEMM 2.725278 N m; gap 0.27% (0.007318 N m). Back-EMF H1 gap 0.01%; peak gap 0.08%. |
| [spm_8p12s_reference_angle30__baseline](../main-20261010-45e0a5c-rerun/fixtures/spm_8p12s_reference_angle30__baseline__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 19.173083 / FEMM 19.234698 N m; gap 0.32% (0.061615 N m). Back-EMF H1 gap 0.14%; peak gap 0.17%. |

### spm_4p12s_simple__baseline

PASS: Mean torque: Magneto2D 0.478269 / FEMM 0.477514 N m; gap 0.16% (0.000755 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_4p12s_simple__high_current

PASS: Mean torque: Magneto2D 0.717225 / FEMM 0.716397 N m; gap 0.12% (0.000828 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_4p12s_simple__tight_airgap

PASS: Mean torque: Magneto2D 0.582697 / FEMM 0.583066 N m; gap 0.06% (0.000370 N m). Back-EMF H1 gap 0.35%; peak gap 0.05%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_4p12s_simple_noload__baseline

PASS: Mean torque: Magneto2D -0.000003 / FEMM -0.002058 N m; gap 99.83% (0.002055 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_4p12s_simple_noload__high_current

PASS: Mean torque: Magneto2D 0.239170 / FEMM 0.238513 N m; gap 0.28% (0.000656 N m). Back-EMF H1 gap 0.01%; peak gap 0.04%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_4p12s_simple_noload__tight_airgap

PASS: Mean torque: Magneto2D -0.000116 / FEMM -0.000104 N m; gap 12.02% (0.000012 N m). Back-EMF H1 gap 0.35%; peak gap 0.05%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p12s_concentrated__baseline

PASS: Mean torque: Magneto2D 2.561836 / FEMM 2.557786 N m; gap 0.16% (0.004050 N m). Back-EMF H1 gap 0.07%; peak gap 0.15%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p12s_concentrated__high_current

PASS: Mean torque: Magneto2D 3.836667 / FEMM 3.833448 N m; gap 0.08% (0.003219 N m). Back-EMF H1 gap 0.07%; peak gap 0.15%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p12s_concentrated__tight_airgap

PASS: Mean torque: Magneto2D 2.717960 / FEMM 2.725278 N m; gap 0.27% (0.007318 N m). Back-EMF H1 gap 0.01%; peak gap 0.08%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p12s_reference_angle30__baseline

PASS: Mean torque: Magneto2D 19.173083 / FEMM 19.234698 N m; gap 0.32% (0.061615 N m). Back-EMF H1 gap 0.14%; peak gap 0.17%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |
## Phase B results - IPM

| Fixture input | Outcome | Measured candidate | Metrics |
| --- | --- | --- | --- |
| [ipm_flat_12s10p_fscw_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_12s10p_fscw_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 4.502358 / FEMM 4.475955 N m; gap 0.59% (0.026403 N m). Back-EMF H1 gap 0.61%; peak gap 0.78%. |
| [ipm_flat_24s16p_industrial_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_24s16p_industrial_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 22.426612 / FEMM 22.557361 N m; gap 0.58% (0.130749 N m). Back-EMF H1 gap 0.18%; peak gap 0.31%. |
| [ipm_flat_4p12s_micro_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_4p12s_micro_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.021444 / FEMM 0.021516 N m; gap 0.33% (0.000072 N m). Back-EMF H1 gap 0.56%; peak gap 0.78%. |
| [ipm_flat_8p12s_fsae_angled_pocket_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 2.484240 / FEMM 2.486783 N m; gap 0.10% (0.002543 N m). Back-EMF H1 gap 0.30%; peak gap 0.73%. |
| [ipm_flat_8p12s_fsae_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_8p12s_fsae_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 2.974150 / FEMM 2.978470 N m; gap 0.15% (0.004320 N m). Back-EMF H1 gap 0.24%; peak gap 0.30%. |
| [ipm_flat_8p12s_fsae_thin_bridge_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 3.678026 / FEMM 3.673380 N m; gap 0.13% (0.004646 N m). Back-EMF H1 gap 0.22%; peak gap 0.45%. |
| [ipm_vshape_8p12s_baseline_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_vshape_8p12s_baseline_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.934474 / FEMM 0.869846 N m; gap 7.43% (0.064628 N m). Back-EMF H1 gap 2.09%; peak gap 6.26%. |
| [ipm_vshape_8p12s_deep_apex_high_output_v1](../ipm-high-output-20261011-af56962/fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1.json) | PASS | `af56962` | Mean torque: Magneto2D 0.625690 / FEMM 0.582518 N m; gap 7.41% (0.043172 N m). Back-EMF H1 gap 3.35%; peak gap 3.95%. |
| [ipm_vshape_8p12s_narrow_angle_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 0.934291 / FEMM 0.897028 N m; gap 4.15% (0.037263 N m). Back-EMF H1 gap 3.54%; peak gap 4.43%. |
| [ipm_vshape_8p12s_pocket_offset_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 1.122768 / FEMM 1.064713 N m; gap 5.45% (0.058054 N m). Back-EMF H1 gap 1.33%; peak gap 3.03%. |
| [ipm_vshape_8p12s_thin_bridge_contract](../main-20261010-45e0a5c-rerun/fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 3.010934 / FEMM 2.957579 N m; gap 1.80% (0.053355 N m). Back-EMF H1 gap 0.85%; peak gap 1.70%. |
| [ipm_vshape_8p12s_wide_angle_high_output_v1](../ipm-high-output-20261011-af56962/fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1.json) | PASS | `af56962` | Mean torque: Magneto2D 0.789964 / FEMM 0.737758 N m; gap 7.08% (0.052205 N m). Back-EMF H1 gap 3.49%; peak gap 3.95%. |

### ipm_flat_12s10p_fscw_contract

PASS: Mean torque: Magneto2D 4.502358 / FEMM 4.475955 N m; gap 0.59% (0.026403 N m). Back-EMF H1 gap 0.61%; peak gap 0.78%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_flat_24s16p_industrial_contract

PASS: Mean torque: Magneto2D 22.426612 / FEMM 22.557361 N m; gap 0.58% (0.130749 N m). Back-EMF H1 gap 0.18%; peak gap 0.31%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_flat_4p12s_micro_contract

PASS: Mean torque: Magneto2D 0.021444 / FEMM 0.021516 N m; gap 0.33% (0.000072 N m). Back-EMF H1 gap 0.56%; peak gap 0.78%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_flat_8p12s_fsae_angled_pocket_contract

PASS: Mean torque: Magneto2D 2.484240 / FEMM 2.486783 N m; gap 0.10% (0.002543 N m). Back-EMF H1 gap 0.30%; peak gap 0.73%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_flat_8p12s_fsae_contract

PASS: Mean torque: Magneto2D 2.974150 / FEMM 2.978470 N m; gap 0.15% (0.004320 N m). Back-EMF H1 gap 0.24%; peak gap 0.30%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_flat_8p12s_fsae_thin_bridge_contract

PASS: Mean torque: Magneto2D 3.678026 / FEMM 3.673380 N m; gap 0.13% (0.004646 N m). Back-EMF H1 gap 0.22%; peak gap 0.45%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_baseline_contract

PASS: Mean torque: Magneto2D 0.934474 / FEMM 0.869846 N m; gap 7.43% (0.064628 N m). Back-EMF H1 gap 2.09%; peak gap 6.26%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_deep_apex_high_output_v1

PASS: Mean torque: Magneto2D 0.625690 / FEMM 0.582518 N m; gap 7.41% (0.043172 N m). Back-EMF H1 gap 3.35%; peak gap 3.95%.

October 11 two-case qualification; full registered grids, public defaults, normal spatial meshes. Candidate `af56962e690ade4816e48f562e380249aac7542e`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../ipm-high-output-20261011-af56962/rows/ipm_vshape_8p12s_deep_apex_high_output_v1.json); SHA-256 `6bfdb6c4af8b6f271a7601554e36319ce3fe1e8a1428c025387f846b6b5f12fb`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_narrow_angle_contract

PASS: Mean torque: Magneto2D 0.934291 / FEMM 0.897028 N m; gap 4.15% (0.037263 N m). Back-EMF H1 gap 3.54%; peak gap 4.43%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_pocket_offset_contract

PASS: Mean torque: Magneto2D 1.122768 / FEMM 1.064713 N m; gap 5.45% (0.058054 N m). Back-EMF H1 gap 1.33%; peak gap 3.03%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_thin_bridge_contract

PASS: Mean torque: Magneto2D 3.010934 / FEMM 2.957579 N m; gap 1.80% (0.053355 N m). Back-EMF H1 gap 0.85%; peak gap 1.70%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### ipm_vshape_8p12s_wide_angle_high_output_v1

PASS: Mean torque: Magneto2D 0.789964 / FEMM 0.737758 N m; gap 7.08% (0.052205 N m). Back-EMF H1 gap 3.49%; peak gap 3.95%.

October 11 two-case qualification; full registered grids, public defaults, normal spatial meshes. Candidate `af56962e690ade4816e48f562e380249aac7542e`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../ipm-high-output-20261011-af56962/rows/ipm_vshape_8p12s_wide_angle_high_output_v1.json); SHA-256 `810e49b9246f08a5811e336e3dd3e18bc580c1386b5fc851a27a073da869297f`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |
## Phase C results - Distributed Winding

| Fixture input | Outcome | Measured candidate | Metrics |
| --- | --- | --- | --- |
| [ornl_prius_2004_ipm](../main-20261010-45e0a5c-rerun/fixtures/ornl_prius_2004_ipm__native.json) | Planned coverage (not yet supported) | `45e0a5c` | The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only. Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support. |
| [spm_12p36s_distributed_femm_validation](../main-20261010-45e0a5c-rerun/fixtures/spm_12p36s_distributed_femm_validation__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 5.044514 / FEMM 5.206070 N m; gap 3.10% (0.161557 N m). Back-EMF H1 gap 0.98%; peak gap 0.59%. |
| [spm_8p24s_distributed_femm_validation](../main-20261010-45e0a5c-rerun/fixtures/spm_8p24s_distributed_femm_validation__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 5.562636 / FEMM 5.624537 N m; gap 1.10% (0.061900 N m). Back-EMF H1 gap 0.51%; peak gap 0.28%. |
| [spm_8p48s_chorded_5_6](../main-20261010-45e0a5c-rerun/fixtures/spm_8p48s_chorded_5_6__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 5.937996 / FEMM 5.979840 N m; gap 0.70% (0.041844 N m). Back-EMF H1 gap 0.80%; peak gap 0.13%. |
| [spm_8p48s_distributed_femm_validation](../main-20261010-45e0a5c-rerun/fixtures/spm_8p48s_distributed_femm_validation__native.json) | PASS | `45e0a5c` | Mean torque: Magneto2D 6.057186 / FEMM 6.097581 N m; gap 0.66% (0.040395 N m). Back-EMF H1 gap 0.87%; peak gap 0.96%. |

### ornl_prius_2004_ipm

Planned coverage (not yet supported): The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only. Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |

### spm_12p36s_distributed_femm_validation

PASS: Mean torque: Magneto2D 5.044514 / FEMM 5.206070 N m; gap 3.10% (0.161557 N m). Back-EMF H1 gap 0.98%; peak gap 0.59%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p24s_distributed_femm_validation

PASS: Mean torque: Magneto2D 5.562636 / FEMM 5.624537 N m; gap 1.10% (0.061900 N m). Back-EMF H1 gap 0.51%; peak gap 0.28%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p48s_chorded_5_6

PASS: Mean torque: Magneto2D 5.937996 / FEMM 5.979840 N m; gap 0.70% (0.041844 N m). Back-EMF H1 gap 0.80%; peak gap 0.13%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |

### spm_8p48s_distributed_femm_validation

PASS: Mean torque: Magneto2D 6.057186 / FEMM 6.097581 N m; gap 0.66% (0.040395 N m). Back-EMF H1 gap 0.87%; peak gap 0.96%.

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque | PASS |
| bemf_fundamental | PASS |
| bemf_peak | PASS |
| torque_method | PASS |
| native_mesh | PASS |
| angle_grids | PASS |
## Phase D results - BLDC

| Fixture input | Outcome | Measured candidate | Metrics |
| --- | --- | --- | --- |
| [spm_14p12s_high_pole](../main-20261010-45e0a5c-rerun/fixtures/spm_14p12s_high_pole__native-standard.json) | PASS | `45e0a5c` | 14/14 gates PASS |
| [spm_4p12s_small](../main-20261010-45e0a5c-rerun/fixtures/spm_4p12s_small__native-standard.json) | PASS | `45e0a5c` | 14/14 gates PASS |
| [spm_8p12s_reference](../main-20261010-45e0a5c-rerun/fixtures/spm_8p12s_reference__native-standard.json) | PASS | `45e0a5c` | 14/14 gates PASS |

### spm_14p12s_high_pole

PASS: 14/14 gates PASS

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque_delta_pct | PASS |
| torque_waveform_nrmse_pct | PASS |
| commutation_transition_delta_samples | PASS |
| power_torque_delta_pct | PASS |
| native_standard_to_fine_mean_torque_delta_pct | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | PASS |
| native_standard_current_properties | PASS |
| native_fine_current_properties | PASS |
| femm_standard_current_properties | PASS |
| analytical_low_current_current_properties | PASS |
| native-standard_golden_current_sequence | PASS |
| native-fine_golden_current_sequence | PASS |
| analytical_golden_current_sequence | PASS |
| femm-standard_golden_current_sequence | PASS |

### spm_4p12s_small

PASS: 14/14 gates PASS

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque_delta_pct | PASS |
| torque_waveform_nrmse_pct | PASS |
| commutation_transition_delta_samples | PASS |
| power_torque_delta_pct | PASS |
| native_standard_to_fine_mean_torque_delta_pct | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | PASS |
| native_standard_current_properties | PASS |
| native_fine_current_properties | PASS |
| femm_standard_current_properties | PASS |
| analytical_low_current_current_properties | PASS |
| native-standard_golden_current_sequence | PASS |
| native-fine_golden_current_sequence | PASS |
| analytical_golden_current_sequence | PASS |
| femm-standard_golden_current_sequence | PASS |

### spm_8p12s_reference

PASS: 14/14 gates PASS

Retained October 10 macOS native rerun against saved October 9 FEMM data. Candidate `45e0a5c7662ade04a4be5519b7e5bac771a6122f`; reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.

[Measured source evidence](../main-20261010-45e0a5c-rerun/benchmark_summary.json); SHA-256 `4185d9dacbc44331cc895863ed9477dcd6e954b07110ae345f96b6c293edfb6d`.

| Gate | Outcome |
| --- | --- |
| mean_torque_delta_pct | PASS |
| torque_waveform_nrmse_pct | PASS |
| commutation_transition_delta_samples | PASS |
| power_torque_delta_pct | PASS |
| native_standard_to_fine_mean_torque_delta_pct | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | PASS |
| native_standard_current_properties | PASS |
| native_fine_current_properties | PASS |
| femm_standard_current_properties | PASS |
| analytical_low_current_current_properties | PASS |
| native-standard_golden_current_sequence | PASS |
| native-fine_golden_current_sequence | PASS |
| analytical_golden_current_sequence | PASS |
| femm-standard_golden_current_sequence | PASS |
