# ORNL 2004 Prius benchmark fixture: correction to primary sources

This is item 3 of [#82](https://github.com/coilemdev/coilem/issues/82): the `ornl_prius_2004_ipm` benchmark request, corrected to the primary-source values from the [Phase A source audit](source-audit.md).

The corrected request is [`benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json`](../../../benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json), registered in [protocol 1.2.0](../../../benchmarks/abcd-v1.2/README.md). The protocol 1.1.0 request and its UNSUPPORTED record are unchanged.

## What changed

| Field | 1.1.0 request | Corrected | Source and class |
| --- | --- | --- | --- |
| Rotor OD | 160.4 | 160.38 | 6.314 in, S5 Fig. 21 (stated) |
| Rotor pocket (HoleM50) | Pyleecan Toyota_Prius values | H0 10.71, H1 1.47, H2 1.75, H3 6.81, W0 41.70, W3 13.68, W4 19.30 | [HoleM50 mapping](holem50-mapping.md): bridge stated; the rest inferred from the figure |
| Magnet size | 18.9 × 6.5 | 19.30 × 6.81 | W4 × H3 of the mapping (inferred from the figure) |
| Magnet grade | `Prius_2004_NdFeB` (Br 1.24 T, μr 1.05, an assumption) | `ORNL_Prius_2004_NdFeB` (Br 1.235 T, μr 1.12) | S4 Fig. 14 demagnetization line (inferred from the figure); see MATERIALS.md |
| Stator bore | 161.9 | 161.93 | 6.375 in, S5 Fig. 21 (stated) |
| Yoke depth | 19.37 | 20.13 | (10.600 − 6.375 − 2 × 1.320) / 2 in (derived from stated) |
| Tooth shoe | none | height 1.02, overhang 0.56 | Tip height 0.040 in (stated); overhang from the 0.076 in mouth (stated) |
| Slot opening above the tips | 2.0 | 3.06 | [Stator mapping](#stator-slot-mapping); callout 0.124 in = 3.15 |
| Tooth width at the yoke | 5.6 | 9.10 | Stator mapping (inferred from the figure); not dimensioned |

Everything else is unchanged from the 1.1.0 request:
- stator OD 269.24 and stack length 83.82 mm
- 48 slots and 8 poles
- the winding: distributed, single layer, 9 turns per coil, series
- M350-50A steel
- the solve settings: 250 A peak at 45°, 3,000 rpm, a 90° loaded sweep in 7.5° steps, a 48-point Back-EMF cycle, and normal mesh

The radial airgap is now 0.775 mm, as derived in Phase A.

## Stator slot mapping

ORNL dimensions the slot only in a detail: mouth 0.076 in, the width above the tips 0.124 in, tip height 0.040 in, depth 1.320 in and a ⌀0.222 in round bottom. Which callout belongs to which feature is read from the figure. The tooth width is not dimensioned.

[`tools/fit_ornl_prius_stator.py`](../../../tools/fit_ornl_prius_stator.py) measures the drawn slot instead. It reads the black stator paths of S5 Fig. 21 in the drawing frame fitted for the rotor (centre offset and the 1.19% plot stretch). It then measures every one of the 48 slots between both walls; data in [`stator-slot-mapping.json`](stator-slot-mapping.json).

| Slot feature | Drawn (median of 48 slots) | Callout |
| --- | --- | --- |
| Mouth | 1.85–1.87 mm | 0.076 in = 1.93 mm |
| Width just above the tips | 3.17 mm | 0.124 in = 3.15 mm |
| Widest, where the round bottom starts | 5.56 mm | ⌀0.222 in = 5.64 mm |

The drawing agrees with every callout within 0.1 mm. The teeth taper from about 7.6 mm at the tips to 9.0 mm at the slot bottom.

coilEM's slot is a straight taper from the bore to the yoke, with an optional shoe. The tool fits its slot opening and tooth width to the drawn walls, with the shoe height and mouth fixed at the callouts:

| Stator set | Drawn-wall residual: RMS | Max |
| --- | --- | --- |
| 1.1.0 request (tooth 5.6 mm, no shoe) | 1.45 mm | 2.84 mm |
| Callouts used directly (opening 3.15, tooth 9.35) | 0.11 mm | 0.21 mm |
| **Fitted to the walls (opening 3.06, tooth 9.10)** | **0.004 mm** | **0.006 mm** |

coilEM's slot has a flat bottom where ORNL's is round, which adds about 3% of slot area. No current flows in the no-load Back-EMF solve, and the teeth are matched.

## Input freeze

Phase B of [#69](https://github.com/coilemdev/coilem/issues/69) requires the model inputs to be frozen before the ORNL comparison runs. The commit that adds this page is that freeze:

- request: `benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json`
- request SHA-256 and canonical input hash: the `fixture_sha256` and `input_sha256` of `ornl_prius_2004_ipm` in [`benchmark_spec.json`](../../../benchmarks/abcd-v1.2/benchmark_spec.json)
- magnet contract: `ORNL_Prius_2004_NdFeB`, Br 1.235 T, μr 1.12
- targets: [`target-back-emf.json`](target-back-emf.json), hash-pinned in the same suite file

No input in this request was chosen by comparing a solve against ORNL's measurements. Every value comes from the sources above or is unchanged from the 1.1.0 request. A later change to any of them makes a new request, and a result from it must be labelled `fitted — not a prediction` if the change was informed by the comparison.

The bands Phase B reports around this nominal prediction are listed in the audit's gap list:
- turns per coil ±1
- magnet Br and size
- steel grade
- end effects
- skew
- magnet temperature
