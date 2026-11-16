# V-shape input interpretation and mesh sensitivity (#285)

The V-shape input clarification and the numerical accuracy question are separate. The bridge input is a **minimum** pocket-to-rotor-surface clearance; the drawn bridge also depends on V Depth, V Angle and slab dimensions. Saved magnet coverage (`magnet_embrace`) does not control this geometry. The app reports the actual clearance and explains the unused input as information, both before solving and in stored results. Mesh sensitivity remains a separate warning.

This study samples three imported V-shape fixture geometries at four existing mesh densities. It measures sensitivity; it does **not** establish mesh convergence, certify a new default, or replace the release qualification/FEMM/hardware comparisons. The mesh-accuracy part of [issue #285](https://github.com/coilemdev/coilem/issues/285) remains open.

## Conditions and provenance

- Numerical source: `a9f6a2302967595553fac73a89a424e062325e51`; source-file hashes and the native binary hash are recorded in the [raw results](VSHAPE_MESH_SENSITIVITY_285.json).
- The collector ran from a frozen checkpoint with those numerical sources. The later Python-client/cache merge was excluded from the matrix. The PR itself is based on the latest release branch.
- The release branch was rebased after this study ran, so neither commit is on it. Both are kept as tags: `evidence/vshape-285-source` for the numerical source above, and `evidence/vshape-285-collector` for the collector checkpoint `2597054e2566ec3e9745c76e1f33a71170ce6578` in the raw results. Fetch them with `git fetch origin tag evidence/vshape-285-source tag evidence/vshape-285-collector`.
- Fixtures: `benchmarks/windows-rc-20261013-1fac3a1/fixtures/ipm_vshape_8p12s_*__native.json`. Each original fixture is hashed; each modified request is retained.
- 50 A **peak**, 30-degree current angle, 3,000 rpm; full 360-degree electrical loaded sweep with 7.5-degree steps. The imported fixtures originally used a 90-degree window at zero current angle, so these are sensitivity measurements, not replacements for their historical benchmark numbers.
- Imported Newton/direct solver settings are retained. Loaded torque, no-load back EMF, apparent d/q inductances and a cogging-period sweep are computed using the existing public rotation convention and reuse.
- Each point runs in a fresh child process. Caches and viewer packaging are suppressed to bound memory; native scalar and slot-excitation reports, meshes and numerical post-processing are retained. Full nonlinear histories and field pictures were not archived, so this is not a nonlinear-convergence audit.
- Platform: `macOS-27.2-arm64-arm-64bit`; Gmsh 4.15.2, NumPy 2.4.6, Pydantic 2.13.4. Elapsed times include contention and are not a speed benchmark.

## Results

Element counts are the counts reported by each solve. Torque is the sampled full-cycle average; back EMF is the phase fundamental in RMS volts (line-to-neutral). Cogging peak-to-peak and the repeated-end mismatch come from the separate cogging-period sweep.

| Fixture | Mesh | Elements | Torque (N m) | Back EMF (V rms) | Ld (mH) | Lq (mH) | Cogging p-p (N m) | End mismatch (N m) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_contract | coarse | 21,784 | 1.220204 | 2.642112 | 0.221433 | 0.289466 | 0.131412 | 0.000989 |
| baseline_contract | normal | 94,688 | 1.117743 | 2.354686 | 0.227687 | 0.293233 | 0.082161 | 0.000618 |
| baseline_contract | fine | 101,874 | 1.115173 | 2.345602 | 0.227457 | 0.293161 | 0.074246 | 1.43e-05 |
| baseline_contract | very_fine | 613,518 | 1.070917 | 2.188228 | 0.228459 | 0.294446 | 0.054880 | 1.87e-07 |
| thin_bridge_contract | coarse | 21,252 | 2.816305 | 7.919788 | 0.211483 | 0.285881 | 1.904986 | 0.00798 |
| thin_bridge_contract | normal | 91,030 | 2.675494 | 7.440947 | 0.212538 | 0.287668 | 1.384946 | 5.36e-05 |
| thin_bridge_contract | fine | 98,594 | 2.669616 | 7.424058 | 0.212225 | 0.287611 | 1.373741 | 0.000106 |
| thin_bridge_contract | very_fine | 591,892 | 2.652485 | 7.353785 | 0.212165 | 0.288123 | 1.208524 | 8.69e-05 |
| wide_angle_high_output_v1 | coarse | 21,772 | 1.174504 | 2.398055 | 0.214975 | 0.287136 | 0.100340 | 0.000156 |
| wide_angle_high_output_v1 | normal | 94,160 | 1.052391 | 2.046657 | 0.221534 | 0.290996 | 0.074584 | 4.2e-05 |
| wide_angle_high_output_v1 | fine | 101,172 | 1.050817 | 2.049111 | 0.221875 | 0.291106 | 0.075506 | 9.86e-06 |
| wide_angle_high_output_v1 | very_fine | 609,718 | 1.005072 | 1.893694 | 0.223312 | 0.292482 | 0.065180 | 1.38e-06 |

Changes from Fine to Very Fine, relative to Fine:

| Fixture | Torque | Back EMF | Cogging p-p |
| --- | ---: | ---: | ---: |
| baseline_contract | -3.97% | -6.71% | -26.08% |
| thin_bridge_contract | -0.64% | -0.95% | -12.03% |
| wide_angle_high_output_v1 | -4.35% | -7.58% | -13.67% |

## Release decision and remaining work

The existing Normal and Fine settings produce similar meshes, so agreement between just those two levels is weak evidence of convergence. Very Fine substantially increases the element count and changes the outputs. A small cogging endpoint mismatch checks repeatability at the period boundary; it does not prove spatial convergence or external accuracy.

This PR preserves numerical mesh defaults and adds an explicit V-shape mesh-sensitivity warning. Promoting the largest tested mesh would select an unproven endpoint and substantially increase solve and viewer memory costs. A follow-up must refine the saturated bridge/pocket region, demonstrate a plateau across at least two further resolutions at a stated torque/back-EMF tolerance, assess cogging separately, and validate runtime/memory plus release qualification before choosing a production default. Issue #285 remains open for that work.

Partial loaded sweeps are also labelled explicitly: their torque and d/q averages describe the sampled window rather than a full-cycle average. This avoids conflating a change in averaging window with a change in mesh.

## Reproduction

Use the pinned dependencies and a release-built Magneto2D executable. Check out the numerical source commit above and copy the collector from this PR into that checkout, then run:

```sh
python -m tools.vshape_mesh_study --out output/vshape-study.json
```

The collector resumes matching point JSON files beside the output and rejects changed solver/source/fixture identities. This historical matrix predates those per-point fingerprints; it records the frozen source and binary hashes separately. Use a fresh output directory when changing sources, requests or the native binary; do not combine results from different solver builds. Run points sequentially: Very Fine is expensive. This diagnostic does not alter benchmark registrations or qualification records.

## Follow-up: cause and corner patch

A later pass refined one mesh region at a time on the same three fixtures and operating point. All rows are in [VSHAPE_CORNER_REFINEMENT_285.json](VSHAPE_CORNER_REFINEMENT_285.json); the collector is `tools/vshape_local_refinement_probe.py`.

- Halving the air-gap size or refining the slot mouths to 0.25 mm moves torque by 0.3% or less. Refining around the magnet and pocket corners moves it by up to 6%.
- With 0.1 mm elements held within 5.5 mm of every corner (about 1.2 million elements), the last refinement step changes torque by 0.4% or less and back EMF by 0.8% or less. These runs are the reference below.
- Holding the fine mesh within only 0.75 to 1.5 mm of each corner gives the same torque and back EMF as 5.5 mm.
- The existing Corner refinement option uses about 0.1 mm elements within 0.3 mm of each corner. On its own it leaves torque up to 7.3% and back EMF up to 14.2% above the reference.

V-shape rotors now always get 0.15 mm elements within 1.5 mm of each magnet and pocket corner, with or without the Corner refinement option (`v_shape_magnet_corner` in `backend/mesh_profiles/gmsh_profiles.json`). Other rotors are unchanged. Difference from the reference, Corner refinement off / on:

| Fixture | Elements | Torque | Back EMF | Cogging p-p |
| --- | ---: | ---: | ---: | ---: |
| baseline_contract | 218,086 / 107,358 | +0.2% / +0.3% | +0.6% / +0.5% | +4.4% / +3.3% |
| thin_bridge_contract | 211,806 / 106,212 | 0.0% / +0.1% | -0.05% / +0.05% | +2.3% / +1.8% |
| wide_angle_high_output_v1 | 209,602 / 109,336 | +0.4% / +0.4% | +1.1% / +0.8% | +1.3% / +1.9% |

Cogging still changes by about 2% on the last reference step, so it is not shown to be converged. The flat IPM fixture `ipm_flat_8p12s_fsae_contract` is within 0.15% of its own fine reference on the Normal mesh and is not changed by the patch.

### Comparison with the stored FEMM references

The six registered V-shape fixtures, solved unchanged (0 degree current angle, 90 degree window, Normal mesh, Corner refinement off) on macOS arm64, against the FEMM values in `benchmarks/qualification-70c5e3404c19`. Differences are coilEM relative to FEMM.

| Fixture | Torque, main | Torque, patch | Back EMF fundamental, main | Back EMF fundamental, patch |
| --- | ---: | ---: | ---: | ---: |
| baseline_contract | +7.0% | -0.7% | +8.3% | -0.9% |
| thin_bridge_contract | +2.6% | +0.6% | +1.1% | -0.3% |
| wide_angle_high_output_v1 | +6.6% | -1.0% | +8.6% | -1.6% |
| deep_apex_high_output_v1 | +5.1% | -1.8% | +8.2% | -1.4% |
| narrow_angle_contract | +4.4% | -0.7% | +4.7% | -0.6% |
| pocket_offset_contract | +5.1% | -0.7% | +8.1% | -0.9% |

The record stores the back-EMF difference but not FEMM's value, so the FEMM back EMF is derived from the main-mesh run on this platform; main-mesh torque here matches the registered Windows value to four digits. This is an indication, not a qualification run: the registered benchmark values and the release qualification are not updated here.
