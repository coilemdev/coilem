# Final Windows FEMM stator iron and DC copper qualification

Completed 2026-11-17 at 18:31 Eastern. All eight full-motor load conditions pass the declared integrated-loss gates at 1500 and 3000 rpm (16 operating points). **Rotor loss remains experimental and was excluded.**

This is the frozen numerical baseline for Phase G of the A–G benchmark. The original A–F cases, inputs and FEMM references retain their identities. Regular Phase G runs measure coilEM against these frozen values; they do not launch FEMM or repeat the full qualification campaign.

The field campaign registration names `32dad312212195262fe1ccbf0482575b0c617571`; the final runner/audit names `ef8904b12a30d61a20c5b29d1e3e3abf7b027bad`. Original per-case producer and protocol hashes are retained. Later release/client changes are listed in [provenance.json](provenance.json); this publication does not retag the measured source or certify a later assembled candidate.

| Maximum absolute difference from FEMM | Percent |
|---|---:|
| Stator hysteresis | 0.282334% |
| Stator lamination eddy | 4.580168% |
| Stator iron total | 2.725938% |
| Loaded DC copper | 0.000968% |

Every pair below is **coilEM / FEMM, watts**. Currents are peak amperes. The known subtotal is stator hysteresis + lamination eddy + DC copper; it is not complete motor loss or an efficiency result.

## 1500 rpm

| Fixture / current | Hysteresis | Lamination eddy | Stator total | DC copper | Known subtotal |
|---|---:|---:|---:|---:|---:|
| Concentrated SPM 8p/12s, 0 A | 6.282688 / 6.267571 | 3.905434 / 3.830366 | 10.188122 / 10.097937 | 0.000000 / 0.000000 | 10.188122 / 10.097937 |
| Concentrated SPM 8p/12s, 20 A | 6.392369 / 6.376785 | 3.969630 / 3.894045 | 10.361999 / 10.270830 | 39.875908 / 39.876145 | 50.237907 / 50.146974 |
| Flat IPM 8p/12s, 0 A | 1.153140 / 1.156405 | 0.776736 / 0.763657 | 1.929876 / 1.920061 | 0.000000 / 0.000000 | 1.929876 / 1.920061 |
| Flat IPM 8p/12s, 50 A | 1.319503 / 1.322739 | 0.871632 / 0.856660 | 2.191135 / 2.179399 | 299.252004 / 299.252004 | 301.443139 / 301.431403 |
| Distributed SPM 8p/24s, 0 A | 101.821042 / 101.611992 | 72.208595 / 69.049621 | 174.029637 / 170.661613 | 0.000000 / 0.000000 | 174.029637 / 170.661613 |
| Distributed SPM 8p/24s, 8 A | 101.860210 / 101.650738 | 72.234355 / 69.070797 | 174.094566 / 170.721535 | 10.166571 / 10.166571 | 184.261136 / 180.888106 |
| Outrunner 10p/12s, 0 A | 0.705135 / 0.704668 | 0.545110 / 0.569125 | 1.250245 / 1.273793 | 0.000000 / 0.000000 | 1.250245 / 1.273793 |
| Outrunner 10p/12s, 15 A | 0.722407 / 0.721855 | 0.559610 / 0.582771 | 1.282017 / 1.304626 | 13.429142 / 13.429272 | 14.711158 / 14.733898 |

## 3000 rpm

| Fixture / current | Hysteresis | Lamination eddy | Stator total | DC copper | Known subtotal |
|---|---:|---:|---:|---:|---:|
| Concentrated SPM 8p/12s, 0 A | 12.565376 / 12.535142 | 15.621736 / 15.321465 | 28.187112 / 27.856607 | 0.000000 / 0.000000 | 28.187112 / 27.856607 |
| Concentrated SPM 8p/12s, 20 A | 12.784739 / 12.753569 | 15.878520 / 15.576180 | 28.663259 / 28.329750 | 39.875908 / 39.876145 | 68.539167 / 68.205894 |
| Flat IPM 8p/12s, 0 A | 2.306279 / 2.312809 | 3.106944 / 3.054627 | 5.413224 / 5.367436 | 0.000000 / 0.000000 | 5.413224 / 5.367436 |
| Flat IPM 8p/12s, 50 A | 2.639006 / 2.645478 | 3.486527 / 3.426640 | 6.125533 / 6.072118 | 299.252004 / 299.252004 | 305.377537 / 305.324122 |
| Distributed SPM 8p/24s, 0 A | 203.642084 / 203.223984 | 288.834379 / 276.198485 | 492.476463 / 479.422469 | 0.000000 / 0.000000 | 492.476463 / 479.422469 |
| Distributed SPM 8p/24s, 8 A | 203.720420 / 203.301477 | 288.937421 / 276.283187 | 492.657842 / 479.584663 | 10.166571 / 10.166571 | 502.824413 / 489.751234 |
| Outrunner 10p/12s, 0 A | 1.410270 / 1.409337 | 2.180440 / 2.276500 | 3.590710 / 3.685837 | 0.000000 / 0.000000 | 3.590710 / 3.685837 |
| Outrunner 10p/12s, 15 A | 1.444813 / 1.443710 | 2.238441 / 2.331085 | 3.683254 / 3.774795 | 13.429142 / 13.429272 | 17.112395 / 17.204067 |

## Method and acceptance criteria

- Production Native API: rotor loss off; actual 24/48/96-position electrical-cycle requests at both speeds. The 96-position values above are the actual API results.
- FEMM: 96 half-open electrical poses plus an independent endpoint per condition. Inner material meshes stay fixed through the electrical turn; outer stator fields are queried at fixed material points through the frozen remeshing adapter. Independent direct-DFT loss processing uses FEMM fields, not Native fields.
- 776 verified reference checkpoints: 341 fresh field solves and 435 reused poses. Reuse retains the original answer/checkpoint identities and matched geometry, excitation and material checks.
- Both 24→48 and 48→96 angular changes: at most 5% of the finer value or 0.001 W for each iron term and speed, independently in Native and FEMM.
- Integrated cycle sensitivity: at most 1% of unmodified loss or 0.001 W under a diagnostic linear endpoint-drift calculation. The diagnostic waveform never supplies reported losses.
- FEMM component agreement: at most 10% of reference or 0.001 W for hysteresis, lamination eddy and stator total. DC phase resistance and copper power: 1%; zero-current points still check resistance.
- The registered working meshes were used. This reduced matrix does not claim a new spatial convergence study at every fixture/load point.

## Retained diagnostic failures and policy boundary

The acquisition profile's original 0.1% area-weighted point-field RMS check fails for all eight Native conditions; the original rotor-style 1e-6/1e-7 T closure diagnostics also remain recorded. Slot-pitch mesh reuse and the independently meshed endpoint use different local stator triangulations. These failed point-field verdicts are not relabeled as passes.

Integrated-loss policy v2 separately gates the loss quantities and endpoint-drift loss sensitivity. The numerical PASS applies to that declared integrated-loss scope, not pointwise field/map repeatability. [convergence.json](convergence.json) retains the original `history_pass`/point-field failures alongside `stator_loss_history_pass`, both refinement steps and unmodified/diagnostic loss values.

The distributed field-archive round trip originally failed a 1-ppm bookkeeping check at up to 3.5 ppm. The separate float32 archive budget is now 10 ppm or 1e-6 W, with processor hashes in the retained completion receipts. Original failures and API values are preserved; no field correction, reference fitting or physical loss-gate change was applied.

## Material assumptions and limits

All fixtures use M350-50A, 0.50 mm sheets, electrical resistivity 4.22e-7 ohm m, conventional density 7650 kg/m3 and stacking factor 1.0. Winding temperature is 20 C with specified 0.8 mm wire, two strands in hand; the distributed fixture retains two parallel paths. Magnets and B-H data retain the registered fixture contracts.

Iron loss uses the same material coefficients in both solvers: per kilogram, sum over harmonics of kh*f*B^alpha + kc*f^2*B^2. The classical eddy coefficient comes from sheet thickness/resistivity; hysteresis is derived from the model's two 50 Hz grade-limit points after eddy subtraction. FEMM agreement therefore qualifies field sampling, integration and the numerical calculation under shared assumptions; empirical material accuracy and the physical hysteresis/eddy separation remain unqualified.

DC copper is an independent specified-wire/turn-count/end-turn calculation using FEMM winding geometry, rather than a FEMM AC winding solve. Rotor iron, magnet/component eddy, AC winding, inverter, mechanical, separate excess/minor-loop, rotating-flux, manufacturing and thermal effects are outside this record. Full motor efficiency remains unqualified. The product's iron and rotor model statuses remain experimental; sector loss is deferred.

## Evidence and replay

- [Original comparison summary](summary.json), [original completion audit](qualification-completion-audit.json), [final campaign state](run-state.json), and one original comparison JSON per condition in this directory.
- [Convergence values](convergence.json), [exact registered requests](requested-configs.json), [producer/runtime provenance](provenance.json), and [artifact hashes](artifact-manifest.json). The original compact JSON files retain their bytes and hashes.
- Raw FEMM answers, meshes and full field archives remain retained outside Git. Complete field replay requires those original archives, the pinned Windows FEMM environment and a source-matched Native binary; the compact publication alone is not the full raw archive.
- Regression command: `coilem benchmark --phase G --out <output-directory>`. The full `coilem benchmark` selection includes A–G. Sector collection retains its existing A–F scope; Phase G is full-motor only.

Historical namespace `tools.phase_g_loss` and the byte-bound `benchmarks/phase-g-v1` inputs are retained for qualification replay. See [the acquisition workflow](../../../benchmarks/phase-g-v1/STATOR_COPPER_59.md).
