# coilEM v0.5.0 evidence index

Evidence update: November 2, 2026. **v0.5.0 is not released.** The current
Windows collection measures clean candidate
`88aae101fd487795e7fe5300737679f4133790fd`; the later evidence publication
does not change that measured pin. [Machine-readable index](evidence.json).

| Evidence | Recorded outcome | Qualification status |
| --- | --- | --- |
| [Physical Windows, protocol 1.6](../windows-v050-20261102-88aae101/README.md) | 52 supported jobs complete; 46 PASS, one planned unsupported; 336/336 gates PASS | Complete candidate measurements; reference review pending |
| [Fresh reference bundle](../windows-v050-20261102-88aae101/reference-bundle/manifest.json) | 46 records at adapter `faced858`; exact retained v3 reproduction on the 29 legacy cases | REVIEW_REQUIRED; the active historical bundle is unchanged |
| [Adapter provenance](../reference-adapters/windows-femm42-v3-20261102/README.md) | Actual recovered adapter, dependencies, FEMM executables and source identities archived with verification | Integrity established; scientific review remains separate |
| [Published Mac comparison](../windows-v050-20261102-88aae101/macos-comparison.txt) | 52 job comparisons; zero available torque/EMF metrics outside registered platform tolerances | Historical pins `5b7cad8` and `f6c9fbb`; no same-candidate raw Mac qualification |
| [v0.4.0 to v0.5.0](../reference-adapters/windows-femm42-v3-20261102/version-comparison.txt) | Shared reference data unchanged; baseline V-shape peak improves, fundamental error grows | V-shape remains experimental; no controlled speed claim |
| [Pyleecan Prius](../../docs/benchmarks/pyleecan-prius-v1/README.md), [residual audit](../../docs/PRIUS_CONVERGENCE_AUDIT_20261030.md) | Historical software collections and corrected convergence audit retained | Candidate source identities still need reconciliation or a candidate collection |

The new Windows compact record is published
[beside its evidence](../windows-v050-20261102-88aae101/windows-x86_64.json),
where it can be reproduced without field solves. The active runtime suite,
frozen bundle, historical platform records and application qualification basis
remain unchanged while reference review and platform qualification are pending.
Passing measurements against unreviewed references do not promote outputs.

The [release qualification assessment](release-qualification.json) remains
**BLOCKED**. It records the active registration's outstanding candidate,
protocol, reference-review, platform and Prius source requirements. Updating
this index does not waive them. The release checker now uses the same canonical
bundle digest as the loader; no acceptance threshold is changed.

Before tagging, complete the reference review and reconcile the registered
qualification evidence, both platform records and Prius source evidence.
The published Mac data remains useful historical evidence with its original
pins and precision; it is not restamped as a measurement of `88aae101`.
Then complete wheel/TestPyPI installation acceptance and the owner release
decision, as tracked in the [release plan](../../docs/RELEASE_0_5_0.md).
No VM replay is required.
