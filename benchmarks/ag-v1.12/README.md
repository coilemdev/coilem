# A–G benchmark, protocol 1.12.0

The default benchmark contains the original 69 [A–F cases](../af-v1.10/README.md)
plus 16 Phase G operating points: four full-motor fixtures, loaded/no-load, at
1500 and 3000 rpm. The A–F inputs, references and numerical gates retain their
bytes and identities. The planned unsupported ORNL case is retained; there are
84 supported reference comparisons in the 85-case selection.

```sh
coilem benchmark --list
coilem benchmark --quick
coilem benchmark --phase G --out loss-benchmark
coilem benchmark --out full-benchmark
```

Quick selection includes one complete-grid case from each of seven phases.
Full selection and registered release CI include all G points. Runs need only
the installed Native solver and packaged scalar references, not FEMM.

G uses the [final Windows FEMM loss qualification](../../docs/qualification/stator-copper-femm-20261117/README.md).
Each job exercises the production stator-loss path with 96 electrical positions,
rotor loss off and declared specified wire/temperature. It checks field
convergence, complete full-motor sampling, iron-component/copper balance,
hysteresis, lamination eddy and stator total against FEMM at 10% or 0.001 W,
and DC phase resistance/copper at 1%. The original 24/48/96 qualification and
endpoint sensitivity evidence is retained; routine G runs do not repeat it.

Rotor loss stays experimental and excluded. Magnet/component eddy, AC winding,
mechanical losses and complete motor efficiency are outside G. The shared
material law stays experimental: this is numerical reference agreement, not
measured material/motor qualification. Original point-field diagnostic failures
remain visible in the qualification record under its integrated-loss policy.

Historical A–F and sector protocol 1.11.0 remain replayable. Sector collection
keeps A–F only and rejects `--sector --phase G`. The
[approved 0.5.9 full-motor measurements](../qualification-9f2ce84ef28d/README.md)
provide the current A–G records for Windows x64 and macOS arm64. The historical
records retain their original measured commits and protocol versions.

Record replay stores all five G quantities. Its initial same-platform numerical
replay bounds are 0.5% or 0.001 W for loss and 1e-6 relative or 1e-9 ohm for
resistance, separate from the frozen FEMM gates. These bounds do not establish
unmeasured cross-platform loss reproducibility.
