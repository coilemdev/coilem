# Retained Windows Phase E evidence — experimental

This packet preserves the existing cogging measurements at public commit
`a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f`: **10 PASS / 2 YELLOW** against the
previously selected FEMM references. It is not a new v0.5.5 native run.

The two YELLOW cases remain:

| Case | Peak-to-peak error | First-harmonic error |
|---|---:|---:|
| 8p24s distributed | 10.7285% | 10.1743% |
| 12p36s distributed | 11.1966% | 9.2421% |

The fixed relative PASS/YELLOW limits remain 10%/20%, with each case's
registered absolute floor. Original normal-reference self-check failures are
preserved separately from the corrected reference selection. No value,
waveform, gate or measurement pin was fitted or reclassified.

The experimental reference bundle is
[`../reference-baselines/phase-e-experimental-20261108`](../reference-baselines/phase-e-experimental-20261108/README.md).
Normal composed benchmark reports include Phase E using that dataset, with an
explicit **experimental / unqualified** badge independent of its numerical
verdict. Phase E supplies no application qualification record and does not
change the reviewed Windows Phase F record or existing A–D qualification.

The [HTML comparison](comparison.html), [Markdown table](comparison.md),
[full numerical comparison](comparison.json) and `native/` projections retain
the original measured identity and raw-artifact digests. The source waveform,
result and provenance artifacts remain in their existing public packet.

```sh
python -m tools.build_phase_e_experimental_packet --check
```

This recomputes all twelve retained comparisons and checks every generated
file and public-privacy constraint without launching a field solver.
