# coilEM v0.5.0 evidence index

Evidence update: November 3, 2026. **v0.5.0 is not released.** The Windows and
macOS collections both measure clean candidate
`88aae101fd487795e7fe5300737679f4133790fd`; the later evidence publication
does not change that measured pin. [Machine-readable index](evidence.json).

| Evidence | Recorded outcome | Qualification status |
| --- | --- | --- |
| [Physical Windows, protocol 1.6](../windows-v050-20261102-88aae101/README.md) | 52 supported jobs complete; 46 PASS, one planned unsupported; 336/336 gates PASS | Complete measurements; reviewed comparison registered |
| [Fresh reference bundle](../windows-v050-20261102-88aae101/reference-bundle/manifest.json) | 46 records at adapter `faced858`; exact retained v3 reproduction on the 29 legacy cases | Original preserved; [reviewed successor](../reference-baselines/protocol16-reviewed-20261103/README.md) is active |
| [Adapter provenance](../reference-adapters/windows-femm42-v3-20261102/README.md) | Actual recovered adapter, dependencies, FEMM executables and source identities archived with verification | Integrity established; registered-parity review and saved-model audits complete |
| [Exact-candidate macOS, protocol 1.6](../candidate-qualification-20261103/macos/report/benchmark_report.md) | 52 supported jobs complete; 46 PASS, one planned unsupported; 336/336 gates PASS; two clean collections bit-identical | Reviewed comparison and [native fields](../macos-v050-20261103-88aae101/native/run_manifest.json) registered |
| [Published Mac comparison](../windows-v050-20261102-88aae101/macos-comparison.txt) | 52 job comparisons; zero available torque/EMF metrics outside registered platform tolerances | Historical pins `5b7cad8` and `f6c9fbb`, kept for history |
| [Owner decisions](owner-decisions.json) | References accepted November 3, 2026; output scopes, V-shape and Ld/Lq decisions | Bound to the registered bundle's identity |
| [v0.4.0 to v0.5.0](../reference-adapters/windows-femm42-v3-20261102/version-comparison.txt) | Shared reference data unchanged; baseline V-shape peak improves, fundamental error grows | V-shape remains experimental; no controlled speed claim |
| [Pyleecan Prius](../../docs/benchmarks/pyleecan-prius-v1/README.md), [residual audit](../../docs/PRIUS_CONVERGENCE_AUDIT_20261030.md) | Historical software collections and corrected convergence audit retained | [Exact-candidate Windows report](../candidate-qualification-20261103/prius/README.md): 17 jobs / 568 field reports, 10/10 software checks PASS |

The [review and candidate qualification update](../candidate-qualification-20261103/README.md)
records the hash-bound reference review and the report-only Windows comparison.
The active suite is protocol 1.6, its reviewed bundle is registered, and the
Windows record matches all 63 guarded physical sources captured before fields.
Historical v0.4 records are preserved byte-for-byte. The reviewer is Codex
assistant; no independent human or laboratory sign-off is claimed.

The [release qualification assessment](release-qualification.json)
**passes**: the candidate, protocol, reviewed bundle, both platform records and
the Prius sources all match. No acceptance threshold is changed. The published
Mac data remains historical evidence with its original pins and precision; it
is not restamped as a measurement of `88aae101`. Wheel/TestPyPI installation
acceptance and the owner's release decision remain, as tracked in the
[release plan](../../docs/RELEASE_0_5_0.md).
No VM replay is required.
