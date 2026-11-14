# coilEM 0.5.8 two-platform qualification

Measured candidate: `78e6f4fc8aa8695c6f3ba1f4ad4eb9f843cf54f9` (coilEM 0.5.8,
Magneto2D 0.6.0). Collection: [CI run 43555487683](https://github.com/coilemdev/coilem/actions/runs/43555487683).
Protocol 1.10.0 uses the existing reviewed, frozen A–F references and gates.

| Platform | A–F | Gates | Separate Prius |
| --- | --- | --- | --- |
| Windows x86-64 | 68 PASS, 1 planned unsupported | 468/468 PASS | 10/10 checks, 17 jobs, 568 field positions |
| macOS arm64 | 68 PASS, 1 planned unsupported | 468/468 PASS | 10/10 checks, 17 jobs, 568 field positions |

The unsupported generic Prius suite input does not replace the separate
complete Prius collection. All collection shards and both joins succeeded.

Trusted tooling from main `19548e1460cd9b2c19c0ea644aa0bf9957d0ddcb` compared
both collections with the previous and owner-approved records. Both
[carry receipts](windows-x86_64/carry-receipt.json) ([macOS](macos-arm64/carry-receipt.json))
are READY: no observations exceed the existing carry limits, no moved-value
exceptions were accepted, and reference-sensitive sources and requests remain
compatible. Original fields, reference bundles and tolerances are unchanged.

- [Windows suite report](windows-x86_64/report/benchmark_report.md) and
  [Prius checks](windows-x86_64/prius/app-results.md).
- [macOS suite report](macos-arm64/report/benchmark_report.md) and
  [Prius checks](macos-arm64/prius/app-results.md).
- [Publication projection](publication-projection.json): only machine-local
  diagnostic paths are redacted in public reports; original and published
  hashes are retained, and report indexes name the public bytes.
- [Release gate result](release-qualification.json).

The measured commit remains the source identity even when later metadata,
CI and evidence-publication commits are added. The strict release gate verifies
that current guarded sources still match it. These are registered software
parity checks, not hardware accuracy or arbitrary-geometry mesh convergence.
The V-shape mesh study and #285's remaining accuracy decision stay open.
